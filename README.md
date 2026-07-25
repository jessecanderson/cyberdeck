# CYBERDECK

[![CI](https://github.com/jessecanderson/cyberdeck/actions/workflows/ci.yml/badge.svg)](https://github.com/jessecanderson/cyberdeck/actions/workflows/ci.yml)

A neon, keyboard-first TUI for running multiple local coding agents. The first
provider uses the experimental Codex app-server protocol over stdio.

## Visual tour

### Agent Command Center

Run independent agent uplinks, follow live state and context telemetry, review
normalized operations, and keep approvals inline with the conversation.

![Cyberdeck Agent Command Center](docs/screenshots/agent-command.svg)

### Journal module

Switch the main deck canvas into a UTF-8 Markdown journal with daily entries,
autosave, search, themes, and mixed English/Japanese writing.

![Cyberdeck Journal module](docs/screenshots/journal.svg)

## Requirements

- Homebrew on macOS for the recommended installation (Python is installed as
  a formula dependency)
- `codex` installed and authenticated (`codex login`)
- Python 3.11+ only when installing from source or with pipx

## Install

First, install the Codex CLI, authenticate it, and verify that it is available:

```bash
codex login
codex --version
```

The recommended installation uses the public Cyberdeck Homebrew tap. Homebrew
adds the tap automatically when you run the fully qualified install command:

```bash
brew install jessecanderson/tap/cyberdeck
cyberdeck --version
cyberdeck
```

Upgrade, reinstall, or remove it with:

```bash
brew update
brew upgrade cyberdeck
brew reinstall cyberdeck
brew uninstall cyberdeck
```

Alternatively, [pipx](https://pipx.pypa.io/stable/) can install the latest
source directly from GitHub while keeping the application isolated:

```bash
pipx install git+https://github.com/jessecanderson/cyberdeck.git
cyberdeck
```

Versioned wheel and source-distribution files are also attached to each
[GitHub Release](https://github.com/jessecanderson/cyberdeck/releases). PyPI is
not currently a supported installation channel.

To install from a local clone instead:

```bash
git clone https://github.com/jessecanderson/cyberdeck.git
cd cyberdeck
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
cyberdeck
```

For development, install the editable package and test dependencies:

```bash
python -m pip install -e '.[dev]'
pytest -q
```

The CI suite verifies Python 3.11 through 3.14 and builds an installable wheel
and source distribution on Python 3.14.

For a pipx installation sourced from GitHub, upgrade or remove it with:

```bash
pipx upgrade cyberdeck-tui
pipx uninstall cyberdeck-tui
```

## Usage

Press `Ctrl+N` to spawn an agent, choose a callsign and working directory, then
enter a prompt. Cyberdeck stores that callsign on the Codex thread itself.
`Ctrl+R` opens the manual Archive Uplink, where non-archived interactive Codex
threads can be searched, multi-selected, and restored. `Ctrl+J` and `Ctrl+K`
cycle between uplinks; `Ctrl+P` opens the searchable Uplink Matrix. Unsent
drafts follow their agent, and Up/Down recalls process-local prompt history.

`Ctrl+G` opens Operative Control for rename, interrupt, retry, disconnect, and
archive actions. Disconnect is reversible through Archive Uplink. `Ctrl+B`
opens Signal Multiplexer for guarded concurrent dispatch to two or more ready
agents.

Local commands begin with `/` and are handled by Cyberdeck rather than sent to
the active module. Start with `/help`; current commands include `/new`,
`/restore`, `/agents`, `/agent`, `/rename`, `/interrupt`, `/retry`,
`/disconnect`, `/archive`, `/dispatch`, `/module`, `/theme`, `/journal`,
`/older`, `/clear`, `/path`, and `/quit`.

## Deck modules

Cyberdeck is organized as a permanent deck shell with switchable workspaces.
The agent command center remains the default module, and live agent states stay
visible in the left rail from every workspace. Select an agent to return to its
command center, press `Ctrl+M` to cycle modules, or use `/module NAME`.

The built-in Journal stores user-owned Markdown rather than a database. It uses
one `YYYY-MM-DD.md` file per day, provides date navigation and content search,
and atomically autosaves its multi-line editor. The main document receives focus
when Journal opens; use `Ctrl+L` for the deck command line, Escape to return to
the editor, and `Ctrl+S` to save immediately. Ordinary deck-prompt text becomes
a timestamped quick entry while Journal is active. Use `/journal YYYY-MM-DD`,
`/today`, and `/save` for direct control.

Journal files are UTF-8 and support Japanese and mixed-language writing,
rendering, reload, and normalized content search. IME composition and glyph
appearance depend on the terminal emulator and installed font.

By default, journal files live in Cyberdeck's platform data directory:

- macOS: `~/Library/Application Support/Cyberdeck/journal`
- Linux: `$XDG_DATA_HOME/cyberdeck/journal` or `~/.local/share/cyberdeck/journal`
- Windows: `%APPDATA%/Cyberdeck/journal`

Set `journal.directory` in Cyberdeck's generated `config.toml` to place the
journal in a Git repository, synced folder, or another location.

The Python `DeckModule` contract is currently provisional and used only by the
built-in modules. Modules declare whether the deck prompt, a workspace editor,
or a view-only canvas owns input, along with their preferred focus target and
save behavior. Loading third-party Python packages will follow after this
contract has been exercised without making an unstable API public.

## Themes

ODS Nightwave remains the default. Themes are data-only TOML files: they can
change semantic colors and allowlisted terminal text treatments, but cannot
execute Python or replace structural TCSS. Open the selector with `/theme`,
apply one with `/theme THEME_ID`, or validate and copy a local file with:

```text
/theme import ./my-theme.toml
```

See [`examples/themes/afterglow.toml`](examples/themes/afterglow.toml) for the
version 1 format. Imported themes are stored beside Cyberdeck's user data and
the active choice is persisted in `config.toml`. If a selected theme is missing
or invalid at startup, Cyberdeck visibly falls back to ODS Nightwave.

## Current scope

- Multiple independent new or restored Codex app-server processes
- Searchable, multi-select restoration with 50-turn history pagination
- Terminal-style Markdown conversation rendering with durable timestamps
- Toggleable normalized command/file/tool operations console (`Ctrl+O`)
- ODS status rails, activity states, background unread counts, and agent switching
- Switchable built-in workspaces with a daily Markdown Journal
- Runtime-selectable, validated data-only themes
- Inline, risk-tiered ICE gates for command and file-change approvals
- Explicit transport-failure visibility and resume-based recovery
- Guarded concurrent dispatch with per-target partial-failure reporting
- Clean provider boundary for future ACP and other agent backends

Codex `app-server` is experimental. The adapter deliberately contains all
protocol-specific behavior so changes do not leak into the UI.

## Provenance

This is an independent implementation created from public documentation and
the locally installed Codex protocol schema. It contains no employer source
code, proprietary assets, or internal documentation.
