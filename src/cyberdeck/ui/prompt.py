"""Wrapping command and message editor for the deck prompt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


class PromptEditor(TextArea):
    """A soft-wrapping prompt with explicit submit and newline actions."""

    BINDINGS: ClassVar = [
        *TextArea.BINDINGS,
        Binding("enter", "submit", "Submit", show=False, priority=True),
        Binding("shift+enter", "newline", "New line", show=False, priority=True),
        Binding("ctrl+j", "newline", "New line", show=False, priority=True),
    ]

    @dataclass
    class Submitted(Message):
        input: PromptEditor
        value: str

        @property
        def control(self) -> PromptEditor:
            return self.input

    def __init__(self, *, placeholder: str, id: str) -> None:
        super().__init__(
            id=id,
            placeholder=placeholder,
            soft_wrap=True,
            tab_behavior="focus",
            show_line_numbers=False,
            compact=True,
            highlight_cursor_line=False,
        )

    @property
    def value(self) -> str:
        """Compatibility value used by prompt history and draft coordination."""
        return self.text

    @value.setter
    def value(self, value: str) -> None:
        self.load_text(value)
        self.cursor_location = self.document.end

    @property
    def cursor_position(self) -> int:
        row, column = self.cursor_location
        return sum(len(self.document[index]) + 1 for index in range(row)) + column

    @cursor_position.setter
    def cursor_position(self, position: int) -> None:
        remaining = max(0, min(position, len(self.text)))
        for row, line in enumerate(self.document.lines):
            if remaining <= len(line):
                self.cursor_location = (row, remaining)
                return
            remaining -= len(line) + 1
        self.cursor_location = self.document.end

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self, self.text))

    def action_newline(self) -> None:
        result = self.replace("\n", *self.selection, maintain_selection_offset=False)
        self.move_cursor(result.end_location)

    @property
    def has_visual_line_above(self) -> bool:
        return self.wrapped_document.location_to_offset(self.cursor_location).y > 0

    @property
    def has_visual_line_below(self) -> bool:
        offset = self.wrapped_document.location_to_offset(self.cursor_location)
        return offset.y < self.wrapped_document.height - 1
