from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path

from .module_registry import ModuleRegistry
from .modules import ModuleContext


def configure_module_parser(subparsers: argparse._SubParsersAction) -> None:
    module = subparsers.add_parser("module", help="manage trusted deck modules")
    actions = module.add_subparsers(dest="module_action", required=True)
    actions.add_parser("list", help="list installed modules")
    info = actions.add_parser("info", help="show module metadata")
    info.add_argument("module_id")
    for name in ("install", "link", "validate"):
        parser = actions.add_parser(name)
        parser.add_argument("specification")
        parser.add_argument("--trust", action="store_true", help="trust and execute package code")
        if name == "install":
            parser.add_argument("--disabled", action="store_true")
    update = actions.add_parser("update")
    update.add_argument("module_id")
    update.add_argument("--trust", action="store_true")
    for name in ("enable", "disable", "remove"):
        parser = actions.add_parser(name)
        parser.add_argument("module_id")
        if name == "remove":
            parser.add_argument("--yes", action="store_true")
    init = actions.add_parser("init", help="scaffold a module package")
    init.add_argument("name")
    init.add_argument("--directory", type=Path, default=Path.cwd())


def run_module_command(args: argparse.Namespace) -> int:
    registry = ModuleRegistry()
    action = args.module_action
    if action == "list":
        if not registry.records:
            print("No external modules installed.")
        for record in sorted(registry.records.values(), key=lambda item: item.id):
            print(f"{record.id:<20} {record.version:<10} {record.status:<14} {record.source}")
        return 0
    if action == "info":
        record = registry.records.get(args.module_id)
        if not record:
            raise SystemExit(f"Module not found: {args.module_id}")
        for label, value in (
            ("ID", record.id),
            ("PACKAGE", record.package),
            ("VERSION", record.version),
            ("SOURCE", record.source),
            ("STATE", record.status),
            ("ERROR", record.error or "--"),
        ):
            print(f"{label:<10} {value}")
        return 0
    if action == "init":
        destination = scaffold_module(args.name, args.directory)
        print(f"Created module project: {destination}")
        return 0
    if action in {"install", "link", "validate"}:
        trusted = args.trust or _confirm_trust(args.specification)
        if not trusted:
            raise SystemExit("Module installation cancelled")
        if action == "validate":
            with tempfile.TemporaryDirectory(prefix="cyberdeck-validate-") as temporary:
                root = Path(temporary)
                isolated = ModuleRegistry(root / "modules", root / "config")
                record, _ = isolated.install(
                    args.specification,
                    lambda module_id: _context(isolated, module_id),
                    enabled=False,
                    trusted=True,
                )
                print(f"{record.id} {record.version} is compatible with module API 1")
            return 0
        record, _ = registry.install(
            args.specification,
            lambda module_id: _context(registry, module_id),
            editable=action == "link",
            enabled=not getattr(args, "disabled", False),
            trusted=True,
        )
        suffix = " (update pending)" if record.pending_environment else ""
        print(f"Installed {record.id} {record.version}{suffix}")
        return 0
    record = registry.records.get(args.module_id)
    if not record:
        raise SystemExit(f"Module not found: {args.module_id}")
    if action == "update":
        if not (args.trust or _confirm_trust(record.source)):
            raise SystemExit("Module update cancelled")
        updated, _ = registry.install(
            record.source,
            lambda module_id: _context(registry, module_id),
            trusted=True,
        )
        print(f"Update staged for {updated.id}; restart Cyberdeck to activate it")
    elif action == "enable":
        registry.set_enabled(record.id, True)
        print(f"Enabled {record.id}")
    elif action == "disable":
        registry.set_enabled(record.id, False)
        print(f"Disabled {record.id}")
    elif action == "remove":
        if (
            not args.yes
            and input(f"Remove {record.id} and its environment? [y/N] ").casefold() != "y"
        ):
            raise SystemExit("Module removal cancelled")
        registry.remove(record.id)
        print(f"Removed {record.id}")
    return 0


def _confirm_trust(specification: str) -> bool:
    print("EXTERNAL MODULE // UNVERIFIED PYTHON CODE")
    print(f"Source: {specification}")
    print("This code runs inside Cyberdeck with your user permissions.")
    return input("Trust and continue? [y/N] ").casefold() == "y"


def _context(registry: ModuleRegistry, module_id: str) -> ModuleContext:
    return ModuleContext(
        module_id=module_id,
        data_directory=registry.root / "data" / module_id,
        config_directory=registry.config_root / module_id,
        notify=lambda message, title="MODULE", severity="information": print(f"{title}: {message}"),
        copy_to_clipboard=lambda _text: None,
        services={},
    )


def scaffold_module(name: str, parent: Path) -> Path:
    module_id = re.sub(r"[^a-z0-9_-]+", "-", name.casefold()).strip("-_")
    if len(module_id) < 2:
        raise ValueError("Module name must contain at least two letters or digits")
    package = module_id.replace("-", "_")
    destination = (parent / f"cyberdeck-module-{module_id}").resolve()
    if destination.exists():
        raise FileExistsError(destination)
    source = destination / "src" / package
    tests = destination / "tests"
    source.mkdir(parents=True)
    tests.mkdir()
    (destination / "pyproject.toml").write_text(
        _PYPROJECT.format(module_id=module_id, package=package), encoding="utf-8"
    )
    (source / "__init__.py").write_text(
        _MODULE_SOURCE.format(module_id=module_id, title=module_id.replace("-", " ").upper()),
        encoding="utf-8",
    )
    (tests / "test_module.py").write_text(
        _TEST_SOURCE.format(package=package, module_id=module_id), encoding="utf-8"
    )
    (destination / "README.md").write_text(
        f"# Cyberdeck Module: {module_id}\n\nInstall with `cyberdeck module link .`.\n",
        encoding="utf-8",
    )
    (destination / ".gitignore").write_text(".venv/\n__pycache__/\n*.egg-info/\n", encoding="utf-8")
    return destination


_PYPROJECT = """[build-system]
requires = ["hatchling>=1.31,<2"]
build-backend = "hatchling.build"

[project]
name = "cyberdeck-module-{module_id}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["cyberdeck-tui>=0.3,<0.4"]

[project.entry-points."cyberdeck.modules"]
{module_id} = "{package}:create_module"

[tool.hatch.build.targets.wheel]
packages = ["src/{package}"]
"""

_MODULE_SOURCE = """from textual.widgets import Static

from cyberdeck.modules import DeckModule, ModuleContext, ModuleManifest


class ExampleModule(DeckModule):
    manifest = ModuleManifest(
        id="{module_id}",
        title="{title}",
        description="External Cyberdeck workspace",
        version="0.1.0",
        requires_cyberdeck=">=0.3,<0.4",
        author="Your Name",
        source="external",
        capabilities=("ui", "storage", "notifications"),
    )

    def __init__(self, context: ModuleContext) -> None:
        self.context = context

    def build(self):
        return Static("MODULE ONLINE")

    async def handle_prompt(self, text: str) -> None:
        self.context.notify(text, self.manifest.title, "information")


def create_module(context: ModuleContext) -> DeckModule:
    return ExampleModule(context)
"""

_TEST_SOURCE = """from pathlib import Path

from {package} import create_module
from cyberdeck.modules import ModuleContext


def test_manifest():
    context = ModuleContext("{module_id}", Path("data"), Path("config"), lambda *_: None, lambda _: None, {{}})
    assert create_module(context).manifest.id == "{module_id}"
"""
