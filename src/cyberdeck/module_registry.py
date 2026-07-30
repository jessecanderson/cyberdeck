from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from . import __version__
from .config import _user_root
from .modules import DeckModule, ModuleContext, ModuleStatus, validate_manifest

ENTRY_POINT_GROUP = "cyberdeck.modules"
REGISTRY_VERSION = 1


@dataclass(slots=True)
class ModuleRecord:
    id: str
    package: str
    version: str
    source: str
    environment: str
    enabled: bool = True
    trusted: bool = True
    status: str = ModuleStatus.ENABLED.value
    error: str | None = None
    pending_environment: str | None = None
    previous_environment: str | None = None
    installed_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ModuleRecord:
        fields = cls.__dataclass_fields__
        return cls(**{key: item for key, item in value.items() if key in fields})  # type: ignore[arg-type]


class ModuleRegistry:
    def __init__(self, root: Path | None = None, config_root: Path | None = None) -> None:
        self.root = root or (_user_root("data") / "modules")
        self.config_root = config_root or (_user_root("config") / "modules")
        self.path = self.config_root / "registry.json"
        self.records: dict[str, ModuleRecord] = {}
        self.errors: list[str] = []
        self.load()

    def load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != REGISTRY_VERSION:
                raise ValueError("unsupported registry schema")
            self.records = {
                item["id"]: ModuleRecord.from_dict(item) for item in payload.get("modules", [])
            }
        except FileNotFoundError:
            self.records = {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
            self.records = {}
            self.errors.append(f"Module registry could not be loaded: {exc}")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": REGISTRY_VERSION,
            "modules": [
                asdict(record) for record in sorted(self.records.values(), key=lambda r: r.id)
            ],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def environment_path(self, record: ModuleRecord, *, pending: bool = False) -> Path:
        relative = record.pending_environment if pending else record.environment
        if not relative:
            raise ValueError("Module has no pending environment")
        return self._contained_environment(relative)

    def _contained_environment(self, relative: str) -> Path:
        resolved = (self.root / relative).resolve()
        if self.root.resolve() not in resolved.parents:
            raise ValueError("Module environment escaped the module root")
        return resolved

    def discover_enabled(
        self, context_factory: Callable[[str], ModuleContext]
    ) -> tuple[dict[str, DeckModule], dict[str, str]]:
        modules: dict[str, DeckModule] = {}
        failures: dict[str, str] = {}
        for record in self.records.values():
            if not record.enabled or not record.trusted:
                continue
            try:
                module, package, package_version = self._load_environment(
                    self.environment_path(record), context_factory
                )
                if module.manifest.id != record.id:
                    raise ValueError(
                        f"Manifest id {module.manifest.id!r} does not match registry id {record.id!r}"
                    )
                record.package = package
                record.version = package_version
                record.status = (
                    ModuleStatus.UPDATE_PENDING.value
                    if record.pending_environment
                    else ModuleStatus.ENABLED.value
                )
                record.error = None
                modules[record.id] = module
                if record.previous_environment:
                    previous = self._contained_environment(record.previous_environment)
                    record.previous_environment = None
                    shutil.rmtree(previous, ignore_errors=True)
            except Exception as exc:  # noqa: BLE001
                if record.previous_environment:
                    failed_environment = self.environment_path(record)
                    record.environment = record.previous_environment
                    record.previous_environment = None
                    try:
                        module, package, package_version = self._load_environment(
                            self.environment_path(record), context_factory
                        )
                        record.package = package
                        record.version = package_version
                        record.status = ModuleStatus.ENABLED.value
                        record.error = None
                        modules[record.id] = module
                        failures[record.id] = f"Update rejected; restored previous version: {exc}"
                        shutil.rmtree(failed_environment, ignore_errors=True)
                        continue
                    except Exception as fallback_exc:  # noqa: BLE001
                        exc = RuntimeError(
                            f"Update failed ({exc}); previous version also failed ({fallback_exc})"
                        )
                record.status = ModuleStatus.FAULTED.value
                record.error = str(exc)
                failures[record.id] = str(exc)
        if failures:
            self.save()
        return modules, failures

    def install(
        self,
        specification: str,
        context_factory: Callable[[str], ModuleContext],
        *,
        editable: bool = False,
        enabled: bool = True,
        trusted: bool = False,
    ) -> tuple[ModuleRecord, DeckModule | None]:
        if not trusted:
            raise PermissionError("Installing modules requires explicit trust")
        self.root.mkdir(parents=True, exist_ok=True)
        staging_root = self.root / ".staging"
        staging_root.mkdir(exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="module-", dir=staging_root))
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(staging)],
                check=True,
                capture_output=True,
                text=True,
            )
            python = self._environment_python(staging)
            command = [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
            ]
            if editable:
                command.append("--editable")
            command.append(specification)
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            self._install_module_dependencies(staging)
            module, package, package_version = self._load_environment(staging, context_factory)
            module_id = module.manifest.id
            existing = self.records.get(module_id)
            timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            relative = f"{module_id}-{timestamp}"
            destination = self.root / relative
            os.replace(staging, destination)
            if existing:
                existing.pending_environment = relative
                existing.status = ModuleStatus.UPDATE_PENDING.value
                existing.error = None
                self.save()
                return existing, None
            record = ModuleRecord(
                id=module_id,
                package=package,
                version=package_version,
                source=specification,
                environment=relative,
                enabled=enabled,
                trusted=True,
                status=(ModuleStatus.ENABLED if enabled else ModuleStatus.DISABLED).value,
                installed_at=datetime.now(UTC).isoformat(),
            )
            self.records[module_id] = record
            self.save()
            return record, module if enabled else None
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def apply_pending_updates(self) -> None:
        changed = False
        for record in self.records.values():
            if not record.pending_environment:
                continue
            previous = self.environment_path(record)
            record.previous_environment = record.environment
            record.environment = record.pending_environment
            record.pending_environment = None
            record.status = (
                ModuleStatus.ENABLED if record.enabled else ModuleStatus.DISABLED
            ).value
            del previous
            changed = True
        if changed:
            self.save()

    def set_enabled(self, module_id: str, enabled: bool) -> ModuleRecord:
        record = self.records[module_id]
        record.enabled = enabled
        record.status = (ModuleStatus.ENABLED if enabled else ModuleStatus.DISABLED).value
        record.error = None
        self.save()
        return record

    def load_record(
        self, module_id: str, context_factory: Callable[[str], ModuleContext]
    ) -> DeckModule:
        record = self.records[module_id]
        module, package, package_version = self._load_environment(
            self.environment_path(record), context_factory
        )
        if module.manifest.id != module_id:
            raise ValueError("Loaded module id does not match registry")
        record.package = package
        record.version = package_version
        record.enabled = True
        record.status = ModuleStatus.ENABLED.value
        record.error = None
        self.save()
        return module

    def remove(self, module_id: str) -> None:
        record = self.records[module_id]
        environments = [self.environment_path(record)]
        if record.pending_environment:
            environments.append(self.environment_path(record, pending=True))
        if record.previous_environment:
            environments.append(self._contained_environment(record.previous_environment))
        self.records.pop(module_id)
        for environment in environments:
            shutil.rmtree(environment, ignore_errors=True)
        self.save()

    def _load_environment(
        self, environment: Path, context_factory: Callable[[str], ModuleContext]
    ) -> tuple[DeckModule, str, str]:
        site_packages = self._site_packages(environment)
        site.addsitedir(str(site_packages))
        candidates: list[tuple[importlib.metadata.EntryPoint, importlib.metadata.Distribution]] = []
        for distribution in importlib.metadata.distributions(path=[str(site_packages)]):
            for entry_point in distribution.entry_points:
                if entry_point.group == ENTRY_POINT_GROUP:
                    candidates.append((entry_point, distribution))
        if len(candidates) != 1:
            raise ValueError(
                f"Expected exactly one {ENTRY_POINT_GROUP} entry point, found {len(candidates)}"
            )
        entry_point, distribution = candidates[0]
        factory = entry_point.load()
        module = factory(context_factory(entry_point.name))
        if not isinstance(module, DeckModule):
            raise TypeError("Module factory must return a DeckModule")
        validate_manifest(module.manifest)
        self._validate_cyberdeck_version(module.manifest.requires_cyberdeck)
        return module, distribution.metadata["Name"], distribution.version

    @staticmethod
    def _validate_cyberdeck_version(specifier: str) -> None:
        try:
            if Version(__version__) not in SpecifierSet(specifier):
                raise ValueError(
                    f"Requires Cyberdeck {specifier}; installed version is {__version__}"
                )
        except (InvalidSpecifier, InvalidVersion) as exc:
            raise ValueError(f"Invalid Cyberdeck compatibility requirement: {specifier}") from exc

    def _install_module_dependencies(self, environment: Path) -> None:
        site_packages = self._site_packages(environment)
        distributions = list(importlib.metadata.distributions(path=[str(site_packages)]))
        module_distributions = [
            distribution
            for distribution in distributions
            if any(point.group == ENTRY_POINT_GROUP for point in distribution.entry_points)
        ]
        if len(module_distributions) != 1:
            raise ValueError(f"Expected one module distribution, found {len(module_distributions)}")
        reserved = {"cyberdeck-tui", "textual", "packaging"}
        requirements: list[str] = []
        for raw in module_distributions[0].requires or []:
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as exc:
                raise ValueError(f"Invalid module dependency: {raw}") from exc
            if requirement.marker and not requirement.marker.evaluate():
                continue
            if requirement.name.casefold() not in reserved:
                requirements.append(raw)
        if not requirements:
            return
        result = subprocess.run(
            [
                str(self._environment_python(environment)),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *requirements,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    @staticmethod
    def _site_packages(environment: Path) -> Path:
        windows = environment / "Lib" / "site-packages"
        if windows.is_dir():
            return windows
        matches = sorted((environment / "lib").glob("python*/site-packages"))
        if len(matches) != 1:
            raise ValueError("Could not locate module environment site-packages")
        return matches[0]

    @staticmethod
    def _environment_python(environment: Path) -> Path:
        windows = environment / "Scripts" / "python.exe"
        return windows if windows.exists() else environment / "bin" / "python"
