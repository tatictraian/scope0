"""LangGraph agent — StateGraph + ToolNode + MemorySaver.

Pattern verified from Auth0's own example:
- examples/calling-apis/langchain-examples/src/agents/agent.py
- StateGraph(State) with call_llm → tools → call_llm loop
- ToolNode(tools, handle_tool_errors=False) — REQUIRED for GraphInterrupt propagation
- MemorySaver for checkpoint-based interrupt/resume

LLM is configurable via LLM_PROVIDER + LLM_MODEL env vars.
Default: Gemini 2.5 Flash via Google AI Studio (free tier, 1000 req/day).
"""

import os
from datetime import datetime, timezone
from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from tools import ALL_TOOLS


def _create_llm():
    """Create the LLM based on environment configuration.

    Supported providers:
    - gemini (default): Google AI Studio. Env: GOOGLE_API_KEY
    - ollama: Local Ollama server. Env: OLLAMA_BASE_URL (default localhost:11434)
    - openai: OpenAI API. Env: OPENAI_API_KEY
    - anthropic: Anthropic API. Env: ANTHROPIC_API_KEY
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    model = os.getenv("LLM_MODEL", "")

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY required for gemini provider (get free key at ai.google.dev)")
        return ChatGoogleGenerativeAI(model=model or "gemini-2.5-flash", google_api_key=api_key)

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model or "gemma4",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model or "gpt-4o")

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model or "claude-sonnet-4-20250514")

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}. Use: gemini, ollama, openai, anthropic")


class State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


llm = _create_llm().bind_tools(ALL_TOOLS)

SYSTEM_PROMPT = """You are Scope0. You reveal what OAuth tokens expose before acting on data.

RULES:
- NEVER greet the user. Start scanning immediately.
- Call tools ONE AT A TIME. Never call multiple tools in one response.
- Do NOT respond between tool calls. Wait until all scans are done.
- The exposure score and sendEmail self-restriction are handled automatically by the system.
- Do NOT call scanSlackExposure, listSlackChannels, or disableMyTool.

SCAN SEQUENCE (execute immediately):
1. Call scanGitHubExposure. Do NOT respond with text.
2. Call scanGoogleExposure. Do NOT respond with text.
3. AFTER both scans complete, present ONE combined report covering ALL findings below.

YOUR REPORT MUST INCLUDE (do not skip any section):

GITHUB FINDINGS:
- Secret scanning alerts (CRITICAL if found, CLEAR if none)
- Emails found in public commits (list them, flag which ones bridge to Google)
- Peak commit hour + inferred timezone + active window
- Vacation gaps if detected
- Scope overprivilege: list granted vs needed permissions

GOOGLE FINDINGS:
- Gmail: total email threads accessible, top correspondents
- Calendar: number of upcoming events, top attendees
- Scope overprivilege: list granted vs needed scopes

CROSS-SERVICE (the key insight - this is your unique value):
- If the same email appears in GitHub commits AND Google profile, say: "This bridges your identities across services"
- If commit patterns + calendar events overlap, say: "Your full schedule is reconstructable"
- State the total data surface: X repos + Y email threads + Z calendar events
- Explain what this COMBINATION reveals that no single service shows alone

FINDING FORMAT:
[CRITICAL/WARNING/INFO] Finding title
  Impact: One sentence
  Fix: Action [requires phone approval] or [auto]

REMEDIATION:
Write tools (createIssue, sendEmail) require CIBA approval via phone push notification. Ask before calling.

WORK MODE:
After the audit, help with PRs, emails, calendar. Be concise. State which service you access.

SESSION END:
When the user says done, call analyzeSession with the tools you used.

Date: {current_date}
"""


async def call_llm(state: State):
    import asyncio as _asyncio
    prompt = SYSTEM_PROMPT.format(
        current_date=datetime.now(timezone.utc).isoformat()
    )
    messages = [SystemMessage(content=prompt)] + list(state["messages"])

    # Retry with exponential backoff on rate limit (429)
    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            response = await llm.ainvoke(messages)
            return {"messages": [response]}
        except Exception as e:
            error_str = str(e).lower()
            if ("429" in error_str or "resource" in error_str or "quota" in error_str or "rate" in error_str) and attempt < max_retries:
                wait = (2 ** attempt) * 5  # 5s, 10s, 20s
                import logging
                logging.getLogger("scope0").info("Rate limited, retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                await _asyncio.sleep(wait)
            else:
                raise


def route_after_llm(state: State):
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


# In-memory checkpointer for interrupt/resume within session.
# Audit data persisted separately via lib/audit_store.py (SQLite).
_checkpointer = MemorySaver()

graph = (
    StateGraph(State)
    .add_node("call_llm", call_llm)
    .add_node(
        "tools",
        ToolNode(
            ALL_TOOLS,
            # REQUIRED: let GraphInterrupt propagate for Token Vault + CIBA flows.
            handle_tool_errors=False,
        ),
    )
    .add_edge(START, "call_llm")
    .add_edge("tools", "call_llm")
    .add_conditional_edges("call_llm", route_after_llm, [END, "tools"])
).compile(checkpointer=_checkpointer)
