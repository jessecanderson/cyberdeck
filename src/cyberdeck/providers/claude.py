from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from .acp import AcpAgentAdapter

ClaudeDeployment = Literal["anthropic", "bedrock", "vertex"]

_RUNTIME_IDS: dict[ClaudeDeployment, str] = {
    "anthropic": "claude",
    "bedrock": "claude-bedrock",
    "vertex": "claude-vertex",
}
_CLOUD_SELECTORS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def claude_environment(
    deployment: ClaudeDeployment,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Select one Claude inference route without inspecting provider credentials."""
    if deployment not in _RUNTIME_IDS:
        raise ValueError(f"Unsupported Claude deployment: {deployment}")
    environment = dict(os.environ if source is None else source)
    for name in _CLOUD_SELECTORS:
        environment.pop(name, None)
    if deployment == "bedrock":
        environment["CLAUDE_CODE_USE_BEDROCK"] = "1"
    elif deployment == "vertex":
        environment["CLAUDE_CODE_USE_VERTEX"] = "1"
    return environment


def _claude_route_settings(deployment: ClaudeDeployment) -> dict[str, str]:
    settings = {name: "0" for name in _CLOUD_SELECTORS}
    if deployment == "bedrock":
        settings["CLAUDE_CODE_USE_BEDROCK"] = "1"
    elif deployment == "vertex":
        settings["CLAUDE_CODE_USE_VERTEX"] = "1"
    return settings


class ClaudeAcpAdapter(AcpAgentAdapter):
    """Claude Agent SDK exposed through the maintained ACP stdio adapter."""

    def __init__(
        self,
        executable: str = "claude-agent-acp",
        *,
        deployment: ClaudeDeployment = "anthropic",
        environment: Mapping[str, str] | None = None,
    ) -> None:
        selected_environment = claude_environment(deployment, environment)
        self._route_settings = _claude_route_settings(deployment)
        super().__init__(
            (executable,),
            provider=_RUNTIME_IDS[deployment],
            environment=selected_environment,
        )

    def _session_params(self, cwd: Path, *, session_id: str | None = None) -> dict[str, Any]:
        params = super()._session_params(cwd, session_id=session_id)
        params["_meta"] = {
            "claudeCode": {
                "options": {
                    # Claude settings files are applied after the subprocess
                    # environment. The adapter's programmatic settings tier keeps
                    # this explicit runtime choice authoritative for the session.
                    "settings": {"env": self._route_settings}
                }
            }
        }
        return params
