from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from cyberdeck.app import CyberdeckApp
from cyberdeck.config import ConfigStore
from cyberdeck.domain import AgentStatus, OperationEntry, OperationState, TranscriptEntry
from cyberdeck.journal import JournalStore
from cyberdeck.manager import AgentManager

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "screenshots"


async def generate() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manager = AgentManager(lambda _state, _event: None)
    ghost = manager.register("ghost", Path("/workspace/cyberdeck"), status=AgentStatus.READY)
    ghost.model_provider = "openai"
    ghost.model = "gpt-5.6-codex"
    ghost.current_activity = "awaiting input"
    ghost.context_tokens = 28_400
    ghost.context_window = 128_000
    ghost.transcript.extend(
        [
            TranscriptEntry("system", "UPLINK ESTABLISHED // workspace containment active"),
            TranscriptEntry("user", "Review the release pipeline and summarize remaining risks."),
            TranscriptEntry(
                "assistant",
                "## Release signal\n\n"
                "The wheel and source archive are reproducible. CI now validates **Python "
                "3.11–3.13**, package metadata, and an installed-command smoke test.\n\n"
                "次の段階：署名付きリリースと Homebrew tap を準備します。",
            ),
        ]
    )
    ghost.operations.extend(
        [
            OperationEntry(
                "commandExecution", "python -m pytest -q", OperationState.SUCCEEDED
            ),
            OperationEntry("fileChange", ".github/workflows/ci.yml", OperationState.SUCCEEDED),
        ]
    )
    neon = manager.register("neon", Path("/workspace/release"), status=AgentStatus.PROCESSING)
    neon.current_activity = "building distributions"
    neon.unread_count = 2
    kitsune = manager.register("kitsune", Path("/workspace/themes"), status=AgentStatus.READY)
    kitsune.current_activity = "awaiting input"

    with TemporaryDirectory(prefix="cyberdeck-screenshots-") as temporary:
        root = Path(temporary)
        app = CyberdeckApp(
            skip_boot=True,
            manager=manager,
            config_store=ConfigStore(root / "config.toml"),
            journal_store=JournalStore(root / "journal"),
        )
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            for state in manager.agents:
                await app._add_agent_item(state, select=state is ghost)
            app._render_active()
            app.query_one("#prompt-prefix").update("operator@ghost:/workspace/cyberdeck $")
            await pilot.pause()
            (OUTPUT / "agent-command.svg").write_text(
                app.export_screenshot(title="Cyberdeck — Agent Command Center"),
                encoding="utf-8",
            )

            await app._switch_module("journal")
            await pilot.pause()
            journal = app.query_one("#journal-editor")
            journal.load_text(
                "# Saturday, July 25, 2026\n\n"
                "## Release log\n\n"
                "Cyberdeck is becoming a modular terminal workspace. Today the deck gained:\n\n"
                "- reproducible wheel and source builds\n"
                "- Python 3.11–3.13 validation\n"
                "- a system manifest for safe diagnostics\n\n"
                "## Next signal\n\n"
                "Prepare the public release, trusted publishing, and Homebrew tap.\n"
                "Keep the deck small, composable, and operator-owned.\n"
            )
            app._journal_loaded_text = journal.text
            app._journal_dirty = False
            journal.move_cursor((14, 18))
            journal.focus()
            await pilot.pause()
            (OUTPUT / "journal.svg").write_text(
                app.export_screenshot(title="Cyberdeck — Journal Module"),
                encoding="utf-8",
            )


if __name__ == "__main__":
    asyncio.run(generate())
