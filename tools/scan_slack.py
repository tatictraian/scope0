"""Slack exposure scanner — channel inventory, workspace membership analysis."""

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_slack
from lib.fga import fga_tool_auth


def _scan_slack_exposure_sync() -> dict:
    """Synchronous scan — runs in a thread via asyncio.to_thread."""
    import httpx

    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access Slack")

    headers = {"Authorization": f"Bearer {token}"}
    results = {}

    # --- Channel inventory ---
    try:
        resp = httpx.get(
            "https://slack.com/api/conversations.list",
            headers=headers,
            params={"types": "public_channel,private_channel", "limit": 100},
            timeout=10.0,
        )
        data = resp.json()
        if data.get("ok"):
            channels = data.get("channels", [])
            results["channels"] = {
                "total": len(channels),
                "public": sum(1 for c in channels if not c.get("is_private")),
                "private": sum(1 for c in channels if c.get("is_private")),
                "names": [c.get("name", "") for c in channels[:20]],
            }
        else:
            results["channels"] = {"error": data.get("error", "unknown"), "total": 0}
    except httpx.HTTPError as e:
        results["channels"] = {"error": str(e), "total": 0}

    # --- User identity ---
    try:
        resp = httpx.get(
            "https://slack.com/api/auth.test",
            headers=headers,
            timeout=10.0,
        )
        data = resp.json()
        if data.get("ok"):
            results["identity"] = {
                "user": data.get("user", ""),
                "team": data.get("team", ""),
                "user_id": data.get("user_id", ""),
                "team_id": data.get("team_id", ""),
            }
        else:
            results["identity"] = {"error": data.get("error", "unknown")}
    except httpx.HTTPError as e:
        results["identity"] = {"error": str(e)}

    # --- Scope analysis ---
    granted_scopes = [
        {"scope": "channels:read", "permits": "View all channel names, topics, purposes"},
        {"scope": "groups:read", "permits": "View all private channel names and membership"},
    ]
    needed_for_scan = {"channels:read"}
    granted_set = {s["scope"] for s in granted_scopes}
    unnecessary = granted_set - needed_for_scan
    overprivilege_pct = round(len(unnecessary) / len(granted_set) * 100) if granted_set else 0

    results["scope_analysis"] = {
        "granted": granted_scopes,
        "needed_for_scan": list(needed_for_scan),
        "unnecessary": list(unnecessary),
        "overprivilege_pct": overprivilege_pct,
        "cross_service_note": (
            "Slack workspace membership reveals organizational structure — "
            "combined with GitHub org and Google Calendar attendees, "
            "the full professional network is mappable"
        ),
    }

    return results


@fga_tool_auth("scanSlackExposure")
async def _scan_slack_exposure() -> dict:
    """Async wrapper: FGA check (async) + sync scan in thread."""
    return await asyncio.to_thread(_scan_slack_exposure_sync)


class ScanSlackExposureSchema(BaseModel):
    pass

scan_slack_exposure_tool = with_slack(
    StructuredTool(
        name="scanSlackExposure",
        args_schema=ScanSlackExposureSchema,
        description=(
            "Scan Slack for exposure: channel inventory (public/private), "
            "workspace identity, scope analysis"
        ),
        coroutine=_scan_slack_exposure,
    )
)
