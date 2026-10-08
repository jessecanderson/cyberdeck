"""Module mounting, lifecycle, and fault presentation."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual import work
from textual.widgets import Label, ListItem, ListView, Static

from ..modules import DeckModule, ModuleContext, ModuleStatus
from .common import ConfirmScreen
from .prompt import PromptEditor


class ModuleLifecycle:
    def _activate_module(self, module_id: str) -> None:
        if module_id not in self.deck_modules:
            self.notify(f"Unknown module: {module_id}", severity="error")
            return
        self.run_worker(self._switch_module(module_id), group="module-switch", exclusive=True)

    async def _switch_module(self, module_id: str) -> None:
        main = self.screen_stack[0]
        previous = self.active_module_id
        if previous == "journal" and previous != module_id and not self._save_journal():
            return
        if previous != module_id:
            await self.deck_modules[previous].deactivate()
        self.active_module_id = module_id
        for candidate, widget in self.module_widgets.items():
            widget.display = candidate == module_id
        ordered = self._ordered_module_ids()
        main.query_one("#modules", ListView).index = next(
            index for index, candidate in enumerate(ordered) if candidate == module_id
        )
        self._refresh_module_labels()
        prompt = main.query_one("#prompt", PromptEditor)
        if module_id == "agents":
            prompt.placeholder = "jack in... type a command or message"
            self._render_active()
        elif module_id == "journal":
            prompt.placeholder = "quick journal entry... or /command"
            main.query_one("#prompt-prefix", Static).update("local@journal:today $")
        else:
            prompt.placeholder = "module input... or /command"
            main.query_one("#prompt-prefix", Static).update(f"local@{module_id}:~ $")
        await self.deck_modules[module_id].activate()
        self.deck_config.active_module = module_id
        if self._persist_preferences:
            try:
                self.config_store.save(self.deck_config)
            except OSError as exc:
                self.notify(str(exc), title="CONFIG WRITE FAILED", severity="warning")
        self._focus_active_workspace()

    def _refresh_module_labels(self) -> None:
        view = self.screen_stack[0].query_one("#modules", ListView)
        ordered = self._ordered_module_ids()
        for item, module_id in zip(view.children, ordered, strict=False):
            labels = list(item.query(Label))
            if labels:
                labels[0].update(self._module_label_id(module_id))

    def _module_label(self, module: DeckModule) -> Text:
        return self._module_label_id(module.manifest.id)

    def _module_label_id(self, module_id: str) -> Text:
        module = self.deck_modules.get(module_id)
        record = self.module_registry.records.get(module_id)
        active = module_id == self.active_module_id
        title = module.manifest.title if module else module_id.upper()
        description = module.manifest.description if module else (record.error or record.package)
        status = (
            "ACTIVE"
            if active
            else "FAULT"
            if record and record.status == ModuleStatus.FAULTED.value
            else "UPDATE"
            if record and record.pending_environment
            else "DISABLED"
            if record and not record.enabled
            else "STANDBY"
        )
        label = Text()
        label.append("● " if active else "◇ ", style="bold #52e891" if active else "#607087")
        label.append(title, style="bold #00e8f2" if active else "#8ba2b3")
        label.append(f"  {status}", style="bold #52e891" if active else "#607087")
        label.append(f"\n  {description}", style="#46566c")
        return label

    @staticmethod
    def _module_widget_id(module_id: str) -> str:
        return "agent-module" if module_id == "agents" else f"{module_id}-module"

    def _ordered_enabled_module_ids(self) -> list[str]:
        return sorted(
            self.deck_modules,
            key=lambda key: (self.deck_modules[key].manifest.order, key),
        )

    def _ordered_module_ids(self) -> list[str]:
        ids = set(self.deck_modules) | set(self.module_registry.records)
        return sorted(
            ids,
            key=lambda key: (
                self.deck_modules[key].manifest.order if key in self.deck_modules else 100,
                key,
            ),
        )

    def _module_context(self, module_id: str) -> ModuleContext:
        return ModuleContext(
            module_id=module_id,
            data_directory=self.module_registry.root / "data" / module_id,
            config_directory=self.module_registry.config_root / module_id,
            notify=lambda message, title="MODULE", severity="information": self.notify(
                message, title=title, severity=severity
            ),
            copy_to_clipboard=self._copy_text,
            services={},
        )

    def _module_state(self, module_id: str) -> str:
        if module_id == self.active_module_id:
            return "active"
        record = self.module_registry.records.get(module_id)
        if record:
            return record.status
        return "bundled"

    def _module_description(self, module_id: str) -> str:
        module = self.deck_modules.get(module_id)
        if module:
            return module.manifest.description
        record = self.module_registry.records[module_id]
        return record.error or record.package

    def _module_management_command(self, action: str, module_id: str) -> None:
        if module_id not in self.module_registry.records:
            self.notify(f"External module not found: {module_id}", severity="error")
            return
        if action == "info":
            record = self.module_registry.records[module_id]
            self.notify(
                f"PACKAGE  {record.package}\nVERSION  {record.version}\n"
                f"SOURCE   {record.source}\nSTATE    {record.status}\n"
                f"ERROR    {record.error or '--'}",
                title=f"MODULE // {module_id.upper()}",
            )
        elif action == "enable":
            self.run_worker(self._enable_external_module(module_id), exclusive=False)
        elif action == "disable":
            self.run_worker(self._disable_external_module(module_id), exclusive=False)
        elif action == "remove":
            self.push_screen(
                ConfirmScreen("REMOVE MODULE", f"Remove {module_id} and its environment?"),
                lambda confirmed: (
                    self.run_worker(self._remove_external_module(module_id), exclusive=False)
                    if confirmed
                    else None
                ),
            )
        elif action == "update":
            record = self.module_registry.records[module_id]
            self._install_external_module(record.source)

    @work(exclusive=False)
    async def _install_external_module(self, specification: str, *, editable: bool = False) -> None:
        self.notify("Resolving package and dependencies", title="MODULE INSTALL")
        record = None
        try:
            record, module = await asyncio.to_thread(
                self.module_registry.install,
                specification,
                self._module_context,
                editable=editable,
                trusted=True,
            )
            if module:
                await self._mount_external_module(module)
                self.notify(
                    f"{record.id} {record.version} mounted and ready",
                    title="MODULE INSTALLED",
                )
            else:
                self.notify(
                    f"{record.id} update staged for next launch",
                    title="UPDATE PENDING",
                )
            await self._sync_module_list()
        except Exception as exc:  # noqa: BLE001
            if (
                record
                and record.id in self.module_registry.records
                and not record.pending_environment
            ):
                record.enabled = False
                record.status = ModuleStatus.FAULTED.value
                record.error = str(exc)
                self.module_registry.save()
                await self._sync_module_list()
            self.notify(str(exc), title="MODULE INSTALL FAILED", severity="error")

    async def _mount_external_module(self, module: DeckModule) -> None:
        module_id = module.manifest.id
        if module_id in self.deck_modules:
            raise ValueError(f"Module id already loaded: {module_id}")
        registered = {
            name
            for item in self.deck_modules.values()
            for name in (c.name for c in item.commands())
        }
        registered.update(self.LOCAL_COMMANDS)
        conflicts = sorted(
            command.name for command in module.commands() if command.name in registered
        )
        if conflicts:
            raise ValueError(f"Module command collision: {', '.join(conflicts)}")
        widget = module.build()
        widget.id = self._module_widget_id(module_id)
        widget.add_class("deck-module")
        widget.display = False
        await (
            self.screen_stack[0]
            .query_one("#main-panel")
            .mount(widget, before=self.screen_stack[0].query_one("#autocomplete"))
        )
        self.deck_modules[module_id] = module
        self.module_widgets[module_id] = widget
        await self._sync_module_list()
        await self._switch_module(module_id)

    async def _enable_external_module(self, module_id: str) -> None:
        if module_id in self.deck_modules:
            self.notify(f"{module_id} is already enabled")
            return
        try:
            module = await asyncio.to_thread(
                self.module_registry.load_record, module_id, self._module_context
            )
            await self._mount_external_module(module)
            self.notify(f"{module_id} enabled", title="MODULE ONLINE")
        except Exception as exc:  # noqa: BLE001
            record = self.module_registry.records[module_id]
            record.status = ModuleStatus.FAULTED.value
            record.error = str(exc)
            self.module_registry.save()
            await self._sync_module_list()
            self.notify(str(exc), title="MODULE FAULT", severity="error")

    async def _disable_external_module(self, module_id: str) -> None:
        if self.active_module_id == module_id:
            await self._switch_module("agents")
        module = self.deck_modules.pop(module_id, None)
        widget = self.module_widgets.pop(module_id, None)
        if module:
            try:
                await asyncio.wait_for(module.deactivate(), timeout=2)
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), title="MODULE DEACTIVATION FAULT", severity="warning")
        if widget:
            await widget.remove()
        self.module_registry.set_enabled(module_id, False)
        await self._sync_module_list()
        self.notify(f"{module_id} disabled", title="MODULE OFFLINE")

    async def _remove_external_module(self, module_id: str) -> None:
        if module_id in self.deck_modules:
            await self._disable_external_module(module_id)
        await asyncio.to_thread(self.module_registry.remove, module_id)
        await self._sync_module_list()
        self.notify(f"{module_id} removed", title="MODULE REMOVED")

    async def _sync_module_list(self) -> None:
        view = self.screen_stack[0].query_one("#modules", ListView)
        selected = self.active_module_id
        view.clear()
        ordered = self._ordered_module_ids()
        for module_id in ordered:
            await view.append(ListItem(Label(self._module_label_id(module_id))))
        if selected in ordered:
            view.index = ordered.index(selected)
