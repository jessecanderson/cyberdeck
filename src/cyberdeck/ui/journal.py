"""Journal editor lifecycle and recovery, independent of agent coordination."""

from __future__ import annotations

from datetime import date, datetime

from textual import on
from textual.widgets import Input, Label, ListItem, ListView, Static, TextArea

from .common import ConfirmScreen


class JournalActions:
    async def _handle_journal_prompt(self, prompt: str) -> None:
        if not self._save_journal():
            return
        try:
            updated = self.journal_store.append_quick_entry(self._journal_day, prompt)
        except (OSError, UnicodeError) as exc:
            self.notify(str(exc), title="JOURNAL WRITE FAILED", severity="error")
            return
        self._journal_loading = True
        self.screen_stack[0].query_one("#journal-editor", TextArea).load_text(updated)
        self._journal_loading = False
        self._journal_dirty = False
        self._journal_loaded_text = updated
        query = self.screen_stack[0].query_one("#journal-search", Input).value
        self._refresh_journal_days(query)
        self.notify("Quick entry recorded", title="JOURNAL")

    async def _activate_journal(self) -> None:
        main = self.screen_stack[0]
        query = main.query_one("#journal-search", Input).value
        self._refresh_journal_days(query)
        if not self._journal_initialized:
            self._load_journal_day(self._journal_day)

    async def _deactivate_journal(self) -> None:
        if self._journal_dirty:
            self._save_journal()

    def _refresh_journal_days(self, query: str = "") -> None:
        days = self.journal_store.days(query)
        today = datetime.now().astimezone().date()
        if not query:
            days = sorted(set(days) | {today, self._journal_day}, reverse=True)
        self._journal_dates = days
        view = self.screen_stack[0].query_one("#journal-days", ListView)
        view.clear()
        for day in days:
            marker = "●" if day == self._journal_day else "○"
            view.append(ListItem(Label(f"{marker} {day.isoformat()}\n  {day:%A}")))
        if days:
            try:
                view.index = days.index(self._journal_day)
            except ValueError:
                view.index = 0

    def _load_journal_day(self, day: date, *, discard: bool = False) -> bool:
        if not discard and not self._save_journal():
            return False
        try:
            content = self.journal_store.read(day)
        except (OSError, UnicodeError) as exc:
            self.notify(str(exc), title="JOURNAL READ FAILED", severity="error")
            return False
        self._journal_day = day
        self._journal_loading = True
        main = self.screen_stack[0]
        main.query_one("#journal-editor", TextArea).load_text(content)
        self._journal_loading = False
        self._journal_dirty = False
        self._journal_loaded_text = content
        self._journal_initialized = True
        main.query_one("#journal-date", Static).update(
            f"{day:%A, %B} {day.day}, {day.year} // {day.isoformat()}"
        )
        if self.active_module_id == "journal":
            main.query_one("#prompt-prefix", Static).update(f"local@journal:{day.isoformat()} $")
        return True

    def _save_journal(self) -> bool:
        if not self._journal_dirty:
            return True
        main = self.screen_stack[0] if self.screen_stack else None
        text = (
            main.query_one("#journal-editor", TextArea).text if main else self._journal_pending_text
        )
        try:
            self.journal_store.write(self._journal_day, text, expected=self._journal_loaded_text)
        except (OSError, UnicodeError) as exc:
            if main:
                main.query_one("#journal-status", Static).update(
                    "UNSAVED // COPY EDITS OR RETRY SAVE"
                )
                self.notify(str(exc), title="JOURNAL WRITE FAILED", severity="error")
            return False
        self._journal_dirty = False
        self._journal_loaded_text = text
        if main:
            main.query_one("#journal-status", Static).update("SAVED // USER OWNED MARKDOWN")
            query = main.query_one("#journal-search", Input).value
            self._refresh_journal_days(query)
        return True

    async def _save_journal_module(self) -> bool:
        saved = self._save_journal()
        if saved:
            self.notify("Entry saved", title="JOURNAL")
        return saved

    @on(TextArea.Changed, "#journal-editor")
    def journal_changed(self) -> None:
        editor = self.screen_stack[0].query_one("#journal-editor", TextArea)
        if self._journal_loading or editor.text == self._journal_loaded_text:
            return
        self._journal_dirty = True
        self._journal_pending_text = editor.text
        self.screen_stack[0].query_one("#journal-status", Static).update(
            "MODIFIED // AUTOSAVE ARMED"
        )
        if self._journal_save_timer is not None:
            self._journal_save_timer.stop()
        self._journal_save_timer = self.set_timer(0.7, self._save_journal)

    @on(Input.Changed, "#journal-search")
    def journal_search_changed(self, event: Input.Changed) -> None:
        self._refresh_journal_days(event.value)

    @on(ListView.Highlighted, "#journal-days")
    def journal_day_highlighted(self, event: ListView.Highlighted) -> None:
        if (
            event.list_view.has_focus
            and event.list_view.index is not None
            and event.list_view.index < len(self._journal_dates)
        ):
            day = self._journal_dates[event.list_view.index]
            if day != self._journal_day:
                self._load_journal_day(day)

    @on(ListView.Selected, "#journal-days")
    def journal_day_selected(self) -> None:
        self.screen_stack[0].query_one("#journal-editor", TextArea).focus()

    async def _command_journal(self, args: list[str]) -> None:
        if args == ["reload"]:
            self.push_screen(
                ConfirmScreen(
                    "RELOAD JOURNAL ENTRY",
                    "Discard unsaved edits and load this entry from disk?\nCopy your edits first if you need them.",
                ),
                lambda confirmed: (
                    self._load_journal_day(self._journal_day, discard=True) if confirmed else None
                ),
            )
            return
        day = datetime.now().astimezone().date()
        if len(args) > 1:
            self.notify("usage: /journal [YYYY-MM-DD|reload]", severity="error")
            return
        if args:
            try:
                day = date.fromisoformat(args[0])
            except ValueError:
                self.notify("usage: /journal [YYYY-MM-DD|reload]", severity="error")
                return
        if self._load_journal_day(day):
            self._activate_module("journal")

    async def _command_today(self, _args: list[str]) -> None:
        await self._command_journal([])

    async def _command_save(self, _args: list[str]) -> None:
        if self.active_module_id != "journal":
            self.notify("Journal is not active", severity="warning")
            return
        await self._save_journal_module()
