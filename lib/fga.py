"""FGA (Fine-Grained Authorization) integration for tool-level access control.

Provides:
- fga_tool_auth(tool_name): decorator factory for tool functions
- can_use_tool(user_id, tool_name): async check for UI status display
- set_tool_access(user_id, tool_name, enabled): async toggle for UI + self-restriction

Import paths verified from auth0-ai-python SDK source:
- FGAAuthorizer: auth0_ai.authorizers.fga_authorizer (fga_authorizer.py:42)
- FGAAuthorizer.create() returns instance(**options) -> decorator(handler) pattern
- instance takes build_query and on_unauthorized as kwargs (fga_authorizer.py:80)
- handler must be a Callable (fga_authorizer.py:82), NOT a BaseTool
- FGA reads creds from env: FGA_STORE_ID, FGA_CLIENT_ID, FGA_CLIENT_SECRET (fga_authorizer.py:48-61)
"""

import os

from langchain_core.runnables import ensure_config
from openfga_sdk import (
    ClientConfiguration,
    OpenFgaClient,
    ConsistencyPreference,
)
from openfga_sdk.client import ClientCheckRequest
from openfga_sdk.credentials import CredentialConfiguration, Credentials

from auth0_ai.authorizers.fga_authorizer import FGAAuthorizer

# Singleton FGA instance — reads credentials from environment
_fga = FGAAuthorizer.create()


def fga_tool_auth(tool_name: str):
    """Returns a decorator that checks FGA authorization before tool execution.

    Uses ensure_config() to read user_id from LangGraph's RunnableConfig context.
    This works because the FGA-decorated function runs INSIDE the LangGraph
    tool execution context where RunnableConfig is active.

    Verified: ensure_config() pattern matches CIBA user_id resolution
    (async_authorizer_base.py:112-117).
    """
    return _fga(
        build_query=lambda _: {
            "user": f"user:{ensure_config().get('configurable', {}).get('user_id', 'unknown')}",
            "relation": "can_use",
            "object": f"tool:{tool_name}",
        },
        on_unauthorized=lambda _: f'Tool "{tool_name}" is currently disabled. The user can enable it in the control panel.',
    )


def _get_fga_client_config() -> ClientConfiguration:
    """Build OpenFGA client configuration from environment variables."""
    return ClientConfiguration(
        api_url=os.getenv("FGA_API_URL", "https://api.us1.fga.dev"),
        store_id=os.getenv("FGA_STORE_ID"),
        credentials=Credentials(
            method="client_credentials",
            configuration=CredentialConfiguration(
                api_issuer=os.getenv("FGA_API_TOKEN_ISSUER", "auth.fga.dev"),
                api_audience=os.getenv("FGA_API_AUDIENCE", "https://api.us1.fga.dev/"),
                client_id=os.getenv("FGA_CLIENT_ID"),
                client_secret=os.getenv("FGA_CLIENT_SECRET"),
            ),
        ),
    )


async def can_use_tool(user_id: str, tool_name: str) -> bool:
    """Check if a user can use a specific tool. Used by /api/tools endpoint.

    Fail-closed: if FGA is unreachable, returns False (tool disabled).
    """
    try:
        config = _get_fga_client_config()
        async with OpenFgaClient(config) as client:
            response = await client.check(
                ClientCheckRequest(
                    user=f"user:{user_id}",
                    relation="can_use",
                    object=f"tool:{tool_name}",
                ),
                {"consistency": ConsistencyPreference.HIGHER_CONSISTENCY},
            )
            return response.allowed
    except Exception as exc:
        import logging
        logging.getLogger("scope0.fga").warning(
            "FGA check failed for tool %s: %s", tool_name, exc
        )
        return False  # Fail-closed: deny access when FGA is unreachable


async def set_tool_access(user_id: str, tool_name: str, enabled: bool) -> None:
    """Write or delete an FGA tuple to enable/disable a tool for a user.

    Used by:
    - POST /api/tools/toggle (user UI toggles)
    - tools/self_restrict.py (agent self-restriction — enabled=False only)

    Raises on FGA failure so caller can handle (UI shows error, agent gets error message).
    """
    from openfga_sdk.client.models import ClientTuple

    config = _get_fga_client_config()
    try:
        async with OpenFgaClient(config) as client:
            tuple_key = ClientTuple(
                user=f"user:{user_id}",
                relation="can_use",
                object=f"tool:{tool_name}",
            )
            if enabled:
                try:
                    await client.write_tuples([tuple_key])
                except Exception as we:
                    if "already existed" not in str(we):
                        raise
            else:
                try:
                    await client.delete_tuples([tuple_key])
                except Exception as de:
                    if "did not exist" not in str(de):
                        raise
    except Exception as exc:
        import logging
        logging.getLogger("scope0.fga").warning(
            "FGA write failed for tool %s: %s", tool_name, exc
        )
        raise
