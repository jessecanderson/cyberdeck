from __future__ import annotations

import os
import unicodedata
from datetime import date, datetime
from pathlib import Path


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

    def write(self, day: date, text: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path_for(day)
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)

    def append_quick_entry(self, day: date, text: str) -> str:
        current = self.read(day).rstrip()
        updated = f"{current}\n\n- **{datetime.now().astimezone():%H:%M}** {text}\n"
        self.write(day, updated)
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
                except OSError:
                    continue
                if needle not in haystack:
                    continue
            results.append(day)
        return sorted(results, reverse=True)
