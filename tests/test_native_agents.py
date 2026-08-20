import json
from pathlib import Path

from cyberdeck.native_agents import MAX_METADATA_BYTES, discover_native_agents


def test_discovers_identity_without_retaining_harness_configuration(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "work"
    codex = home / ".codex" / "agents" / "reviewer.toml"
    codex.parent.mkdir(parents=True)
    codex.write_text('name = "Reviewer"\ndescription = "Checks changes"\ninstructions = "secret"\n')
    kiro = workspace / ".kiro" / "agents" / "security" / "audit.json"
    kiro.parent.mkdir(parents=True)
    kiro.write_text(
        json.dumps(
            {
                "name": "Audit",
                "description": "Audits code",
                "hooks": ["private"],
                "mcpServers": {"secret": {}},
                "permissions": ["all"],
            }
        )
    )

    catalog = discover_native_agents(workspace, home=home)

    assert [(row.runtime_id, row.native_id) for row in catalog.agents] == [
        ("codex", "reviewer"),
        ("kiro", "security/audit"),
    ]
    assert catalog.agents[0].launch_supported is False
    assert catalog.agents[1].launch_supported is True
    assert not hasattr(catalog.agents[0], "instructions")
    assert not hasattr(catalog.agents[1], "permissions")


def test_kiro_markdown_and_workspace_precedence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "work"
    personal = home / ".kiro" / "agents" / "team" / "review.md"
    personal.parent.mkdir(parents=True)
    personal.write_text("---\nname: Personal\ndescription: Personal agent\n---\n# ignored")
    project = workspace / ".kiro" / "agents" / "team" / "review.md"
    project.parent.mkdir(parents=True)
    project.write_text("---\nname: Workspace\ndescription: Project agent\n---\n# ignored")

    catalog = discover_native_agents(workspace, home=home)

    assert len(catalog.agents) == 1
    assert catalog.agents[0].native_id == "team/review"
    assert catalog.agents[0].display_name == "Workspace"
    assert catalog.agents[0].scope == "workspace"


def test_malformed_oversized_and_escaping_files_are_diagnostics(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "work"
    root = home / ".kiro" / "agents"
    root.mkdir(parents=True)
    (root / "bad.json").write_text("{")
    (root / "large.json").write_bytes(b"x" * (MAX_METADATA_BYTES + 1))
    outside = tmp_path / "outside.json"
    outside.write_text('{"name":"Outside","description":"No"}')
    (root / "escape.json").symlink_to(outside)
    valid = root / "valid.json"
    valid.write_text('{"name":"Valid","description":"Yes"}')

    catalog = discover_native_agents(workspace, home=home)

    assert [row.native_id for row in catalog.agents] == ["valid"]
    assert len(catalog.diagnostics) == 3


def test_identical_personal_and_workspace_roots_are_not_duplicated(tmp_path: Path) -> None:
    codex = tmp_path / ".codex" / "agents" / "reviewer.toml"
    codex.parent.mkdir(parents=True)
    codex.write_text('name = "Reviewer"\ndescription = "Checks code"')
    kiro = tmp_path / ".kiro" / "agents" / "reviewer.json"
    kiro.parent.mkdir(parents=True)
    kiro.write_text('{"name":"Reviewer","description":"Checks code"}')

    catalog = discover_native_agents(tmp_path, home=tmp_path)

    assert [(row.runtime_id, row.native_id, row.scope) for row in catalog.agents] == [
        ("codex", "reviewer", "workspace"),
        ("kiro", "reviewer", "workspace"),
    ]


def test_duplicate_kiro_id_in_one_scope_is_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "home" / ".kiro" / "agents"
    root.mkdir(parents=True)
    (root / "reviewer.json").write_text('{"name":"JSON Reviewer","description":"First definition"}')
    (root / "reviewer.md").write_text(
        "---\nname: Markdown Reviewer\ndescription: Duplicate definition\n---"
    )

    catalog = discover_native_agents(tmp_path / "work", home=tmp_path / "home")

    assert len(catalog.agents) == 1
    assert catalog.agents[0].display_name == "JSON Reviewer"
    assert "duplicate native agent id" in catalog.diagnostics[0].message
