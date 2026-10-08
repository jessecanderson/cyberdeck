from __future__ import annotations

import os
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path


class JournalConflictError(OSError):
    """The file changed outside this editor since it was loaded."""


class JournalStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, day: date) -> Path:
        return self.directory / f"{day.isoformat()}.md"

    def read(self, day: date) -> str:
        try:
            return self.path_for(day).read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"# {day:%A, %B} {day.day}, {day.year}\n\n"

    def write(self, day: date, text: str, *, expected: str | None = None) -> None:
        if expected is not None and self.read(day) != expected:
            raise JournalConflictError(
                "Entry changed on disk. Copy your edits before reopening the entry."
            )
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path_for(day)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def append_quick_entry(self, day: date, text: str) -> str:
        original = self.read(day)
        current = original.rstrip()
        updated = f"{current}\n\n- **{datetime.now().astimezone():%H:%M}** {text}\n"
        self.write(day, updated, expected=original)
        return updated

    def days(self, query: str = "") -> list[date]:
        if not self.directory.exists():
            return []
        needle = unicodedata.normalize("NFC", query).casefold().strip()
        results: list[date] = []
        for path in self.directory.glob("????-??-??.md"):
            try:
                day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if needle:
                try:
                    haystack = unicodedata.normalize(
                        "NFC", f"{path.stem}\n{path.read_text(encoding='utf-8')}"
                    ).casefold()
                except (OSError, UnicodeError):
                    continue
                if needle not in haystack:
                    continue
            results.append(day)
        return sorted(results, reverse=True)
