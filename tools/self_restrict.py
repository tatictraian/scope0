"""Agent self-restriction tool — voluntarily disables its own capabilities.

ONE-DIRECTIONAL ONLY: can disable, CANNOT re-enable.
Re-enabling requires the USER clicking the toggle in the UI.
Enforced by design: there is no enableMyTool function.
Even if the agent is jailbroken/prompt-injected, it has no mechanism to undo restrictions.

No FGA/TokenVault/CIBA wrapping — this tool is always available.
Must be async because set_tool_access uses OpenFgaClient which is async.
Uses StructuredTool's coroutine parameter (not func) for async execution.
"""

from langchain_core.runnables import ensure_config
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lib.fga import set_tool_access


async def _disable_my_tool(tool_name: str, reason: str) -> dict:
    """Voluntarily disable one of the agent's own tools via FGA.

    Args:
        tool_name: The tool to disable (e.g. "sendEmail", "createIssue")
        reason: Why the agent is disabling this tool
    """
    user_id = ensure_config().get("configurable", {}).get("user_id")
    if not user_id:
        return {"error": "Cannot determine user context for self-restriction"}

    # False ONLY — hardcoded. No enable path exists.
    await set_tool_access(user_id, tool_name, False)
    return {
        "disabled": tool_name,
        "reason": reason,
        "note": "Re-enabling requires the user to toggle in the control panel",
    }


class DisableMyToolSchema(BaseModel):
    tool_name: str = Field(description="Tool to disable (e.g. sendEmail, createIssue)")
    reason: str = Field(description="Why this tool is being disabled")

disable_my_tool = StructuredTool(
    name="disableMyTool",
    description=(
        "Voluntarily disable one of your own tools via FGA. "
        "ONE-DIRECTIONAL: can only disable, cannot re-enable. "
        "Use after exposure audit to enforce least privilege."
    ),
    args_schema=DisableMyToolSchema,
    coroutine=_disable_my_tool,
)
