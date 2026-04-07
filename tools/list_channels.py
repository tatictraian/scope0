"""List Slack channels the authenticated user has access to."""

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_slack
from lib.fga import fga_tool_auth


def _list_slack_channels_sync(include_private: bool = False) -> dict:
    """List Slack channels."""
    import httpx

    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access Slack")

    headers = {"Authorization": f"Bearer {token}"}
    types = "public_channel,private_channel" if include_private else "public_channel"

    try:
        resp = httpx.get(
            "https://slack.com/api/conversations.list",
            headers=headers,
            params={"types": types, "limit": 50},
            timeout=10.0,
        )
        data = resp.json()
        if data.get("ok"):
            channels = data.get("channels", [])
            return {
                "channels": [
                    {
                        "name": c.get("name", ""),
                        "topic": c.get("topic", {}).get("value", ""),
                        "purpose": c.get("purpose", {}).get("value", ""),
                        "is_private": c.get("is_private", False),
                        "num_members": c.get("num_members", 0),
                    }
                    for c in channels
                ],
                "total": len(channels),
            }
        else:
            return {"error": data.get("error", "unknown"), "channels": []}
    except httpx.HTTPError as e:
        if "invalid_auth" in str(e):
            raise TokenVaultError("Authorization required to access Slack")
        return {"error": str(e), "channels": []}


@fga_tool_auth("listSlackChannels")
async def _list_slack_channels(include_private: bool = False) -> dict:
    return await asyncio.to_thread(_list_slack_channels_sync, include_private)


class ListSlackChannelsSchema(BaseModel):
    include_private: bool = Field(default=False, description="Include private channels")

list_slack_channels_tool = with_slack(
    StructuredTool(
        name="listSlackChannels",
        description="List Slack channels. Set include_private=True to include private channels.",
        args_schema=ListSlackChannelsSchema,
        coroutine=_list_slack_channels,
    )
)
