from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from textual.color import Color
from textual.theme import Theme

from .config import user_theme_directory

REQUIRED_COLORS = {"primary", "background", "surface", "foreground", "muted"}
OPTIONAL_COLORS = {"secondary", "accent", "success", "warning", "error", "panel"}
ALLOWED_STYLES = {"bold", "dim", "italic", "bold italic", "none"}
ALLOWED_STYLE_KEYS = {"heading", "muted"}
ALLOWED_TOP_LEVEL = {"schema_version", "id", "name", "author", "colors", "styles"}


@dataclass(frozen=True, slots=True)
class DeckTheme:
    id: str
    name: str
    author: str = "Unknown"
    colors: dict[str, str] = field(default_factory=dict)
    styles: dict[str, str] = field(default_factory=dict)

    def textual_theme(self) -> Theme:
        values = self.colors
        variables = {
            "muted": values["muted"],
            "deck-heading-style": self.styles.get("heading", "bold"),
            "deck-muted-style": self.styles.get("muted", "dim"),
        }
        return Theme(
            name=self.id,
            primary=values["primary"],
            secondary=values.get("secondary"),
            accent=values.get("accent"),
            success=values.get("success"),
            warning=values.get("warning"),
            error=values.get("error"),
            foreground=values["foreground"],
            background=values["background"],
            surface=values["surface"],
            panel=values.get("panel"),
            variables=variables,
            dark=True,
        )


ODS_THEME = DeckTheme(
    "ods",
    "ODS Nightwave",
    "Open Deck Systems",
    colors={
        "primary": "#00e8f2",
        "secondary": "#e62acb",
        "accent": "#e62acb",
        "success": "#52e891",
        "warning": "#e9b949",
        "error": "#ff3b4f",
        "foreground": "#cce7ed",
        "background": "#03050a",
        "surface": "#070c14",
        "panel": "#0a1220",
        "muted": "#607087",
    },
    styles={"heading": "bold", "muted": "dim"},
)


def load_theme(path: Path) -> DeckTheme:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Unable to read theme: {exc}") from exc
    if data.get("schema_version") != 1:
        raise ValueError("Theme schema_version must be 1")
    unknown_sections = data.keys() - ALLOWED_TOP_LEVEL
    if unknown_sections:
        raise ValueError("Unknown theme sections: " + ", ".join(sorted(unknown_sections)))
    theme_id = str(data.get("id", "")).strip().lower()
    if not theme_id or not all(character.isalnum() or character in "-_" for character in theme_id):
        raise ValueError("Theme id must contain only letters, numbers, '-' or '_'")
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("Theme name is required")
    color_data = data.get("colors", {})
    style_data = data.get("styles", {})
    if not isinstance(color_data, dict) or not isinstance(style_data, dict):
        raise ValueError("Theme colors and styles must be TOML tables")  # noqa: TRY004
    colors = {str(key): str(value) for key, value in color_data.items()}
    missing = REQUIRED_COLORS - colors.keys()
    unknown = colors.keys() - REQUIRED_COLORS - OPTIONAL_COLORS
    if missing:
        raise ValueError("Missing theme colors: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError("Unknown theme colors: " + ", ".join(sorted(unknown)))
    for key, value in colors.items():
        try:
            Color.parse(value)
        except Exception as exc:
            raise ValueError(f"Invalid color for {key}: {value}") from exc
    styles = {str(key): str(value) for key, value in style_data.items()}
    unknown_styles = styles.keys() - ALLOWED_STYLE_KEYS
    if unknown_styles:
        raise ValueError("Unknown text styles: " + ", ".join(sorted(unknown_styles)))
    invalid = {value for value in styles.values() if value not in ALLOWED_STYLES}
    if invalid:
        raise ValueError("Invalid text styles: " + ", ".join(sorted(invalid)))
    return DeckTheme(theme_id, name, str(data.get("author", "Unknown")), colors, styles)


def discover_themes(directory: Path | None = None) -> tuple[dict[str, DeckTheme], list[str]]:
    themes = {ODS_THEME.id: ODS_THEME}
    errors: list[str] = []
    root = directory or user_theme_directory()
    if root.exists():
        for path in sorted(root.glob("*.toml")):
            try:
                theme = load_theme(path)
                themes[theme.id] = theme
            except ValueError as exc:
                errors.append(f"{path.name}: {exc}")
    return themes, errors


def import_theme(
    source: Path, directory: Path | None = None, *, replace: bool = False
) -> DeckTheme:
    theme = load_theme(source)
    root = directory or user_theme_directory()
    target = root / f"{theme.id}.toml"
    if target.exists() and not replace:
        raise FileExistsError(theme.id)
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return theme
