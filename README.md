# CYBERDECK

A neon, keyboard-first TUI for running multiple local coding agents. The first
provider uses the experimental Codex app-server protocol over stdio.

## Requirements

- Python 3.11+ (the repository pins pyenv to 3.13.0)
- `codex` installed and authenticated (`codex login`)

## Install

First, install the Codex CLI, authenticate it, and verify that it is available:

```bash
codex login
codex --version
```

The simplest Cyberdeck installation uses
[pipx](https://pipx.pypa.io/stable/), which keeps the application isolated
while exposing the `cyberdeck` command globally:

```bash
pipx install git+https://github.com/jessecanderson/cyberdeck.git
cyberdeck
```

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

To upgrade or remove a pipx installation:

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
the active agent. Start with `/help`; current commands include `/new`, `/restore`,
`/agents`, `/agent`, `/rename`, `/interrupt`, `/retry`, `/disconnect`,
`/archive`, `/dispatch`, `/older`, `/clear`, `/path`, and `/quit`.

## Current scope

- Multiple independent new or restored Codex app-server processes
- Searchable, multi-select restoration with 50-turn history pagination
- Terminal-style Markdown conversation rendering with durable timestamps
- Toggleable normalized command/file/tool operations console (`Ctrl+O`)
- ODS status rails, activity states, background unread counts, and agent switching
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
