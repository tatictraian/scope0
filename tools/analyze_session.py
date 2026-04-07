"""Session analysis tool — scope utilization, before/after score delta.

Pure computation — no Auth0 wrappers, no FGA, always available.
"""

import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


def _analyze_session(
    tools_used: str,
    github_scopes_granted: str = '["repo", "read:user"]',
    google_scopes_granted: str = '["gmail.readonly", "calendar.events.readonly"]',
    initial_score: int = 0,
    current_score: int = 0,
) -> dict:
    """Analyze the current session's scope utilization and exposure delta.

    Args:
        tools_used: JSON array of tool names that were called this session
        github_scopes_granted: JSON array of GitHub OAuth scopes granted
        google_scopes_granted: JSON array of Google OAuth scopes granted
        initial_score: Exposure score at start of session
        current_score: Exposure score now (after remediation)
    """
    try:
        used = json.loads(tools_used) if isinstance(tools_used, str) else tools_used
    except (json.JSONDecodeError, TypeError):
        used = []
    try:
        gh_scopes = json.loads(github_scopes_granted) if isinstance(github_scopes_granted, str) else github_scopes_granted
    except (json.JSONDecodeError, TypeError):
        gh_scopes = []
    try:
        go_scopes = json.loads(google_scopes_granted) if isinstance(google_scopes_granted, str) else google_scopes_granted
    except (json.JSONDecodeError, TypeError):
        go_scopes = []

    # Map tools to the scopes they actually need
    tool_scope_map = {
        "scanGitHubExposure": {"github": ["repo", "read:user"]},
        "listPullRequests": {"github": ["repo"]},
        "createIssue": {"github": ["repo"]},
        "scanGoogleExposure": {"google": ["gmail.readonly", "calendar.events.readonly"]},
        "searchEmails": {"google": ["gmail.readonly"]},
        "listCalendarEvents": {"google": ["calendar.events.readonly"]},
        "sendEmail": {"google": ["gmail.send"]},
    }

    # Compute scopes actually needed by tools that were used
    github_needed = set()
    google_needed = set()
    for tool_name in used:
        scopes = tool_scope_map.get(tool_name, {})
        github_needed.update(scopes.get("github", []))
        google_needed.update(scopes.get("google", []))

    gh_granted_set = set(gh_scopes)
    go_granted_set = set(go_scopes)

    gh_unused = gh_granted_set - github_needed
    go_unused = go_granted_set - google_needed

    gh_utilization = (
        round(len(github_needed) / len(gh_granted_set) * 100)
        if gh_granted_set
        else 0
    )
    go_utilization = (
        round(len(google_needed) / len(go_granted_set) * 100)
        if go_granted_set
        else 0
    )

    return {
        "github": {
            "scopes_granted": list(gh_granted_set),
            "scopes_used": list(github_needed),
            "scopes_unused": list(gh_unused),
            "utilization_pct": gh_utilization,
        },
        "google": {
            "scopes_granted": list(go_granted_set),
            "scopes_used": list(google_needed),
            "scopes_unused": list(go_unused),
            "utilization_pct": go_utilization,
        },
        "tools_used": used,
        "tools_count": len(used),
        "exposure_delta": {
            "initial": initial_score,
            "current": current_score,
            "change": current_score - initial_score,
        },
    }


class AnalyzeSessionSchema(BaseModel):
    tools_used: str = Field(description="JSON array of tool names called this session")
    github_scopes_granted: str = Field(default='["repo", "read:user"]', description="JSON array of GitHub scopes")
    google_scopes_granted: str = Field(default='["gmail.readonly", "calendar.events.readonly"]', description="JSON array of Google scopes")
    initial_score: int = Field(default=0, description="Exposure score at session start")
    current_score: int = Field(default=0, description="Current exposure score")

analyze_session_tool = StructuredTool(
    name="analyzeSession",
    description=(
        "Analyze the current session: scope utilization (granted vs used per service) "
        "and exposure score delta (before/after remediation)."
    ),
    args_schema=AnalyzeSessionSchema,
    func=_analyze_session,
)
