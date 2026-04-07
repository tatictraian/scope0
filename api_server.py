"""Scope0 — aiohttp application server.

Serves the dashboard, handles Auth0 OAuth, streams LangGraph events via SSE.

Key patterns (verified from SDK source + Auth0 example):
- graph.astream(stream_mode=["messages", "updates"]) for real-time streaming + interrupt detection
- Interrupts surface in "__interrupt__" key in update chunks (NOT raised as exceptions)
- Resume via Command(resume='') with same thread_id config (Auth0 example app.py:88)
- Auth0Interrupt.is_interrupt() checks interrupt.get("name") == "AUTH0_AI_INTERRUPT"
- Token Vault interrupt code: "TOKEN_VAULT_ERROR" (token_vault_interrupt.py:11)
- CIBA interrupt codes: "ASYNC_AUTHORIZATION_PENDING", "ASYNC_AUTHORIZATION_POLLING_ERROR"
  (async_authorization_interrupts.py:73,85)
"""

import asyncio
import base64
import json
import logging
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from aiohttp import web
import aiohttp_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.types import Command

from auth0_ai.interrupts.auth0_interrupt import Auth0Interrupt
from lib.agent import graph
from lib.audit_store import store_scan_result, store_exposure_score, store_self_restriction, get_audit_timeline, save_last_session, get_last_session
from lib.auth0_web import setup_auth_routes
from lib.fga import can_use_tool, set_tool_access

# --- App setup ---

app = web.Application()

session_secret = os.environ.get("SESSION_SECRET")
if not session_secret:
    raise RuntimeError("SESSION_SECRET env var required (generate with: openssl rand -hex 32)")

# Derive Fernet key from SESSION_SECRET
# If hex string (from openssl rand -hex 32), decode to bytes first
try:
    secret_bytes = bytes.fromhex(session_secret)
except ValueError:
    secret_bytes = session_secret.encode()
fernet_key = base64.urlsafe_b64encode(secret_bytes[:32].ljust(32, b"\0")).decode()
aiohttp_session.setup(
    app,
    EncryptedCookieStorage(
        fernet_key,
        cookie_name="scope0_session",
        max_age=24 * 60 * 60,  # 24 hours
    ),
)

# --- Dashboard assembly ---
# Load all static files at startup, assemble into single HTTP response.
# Proven pattern from CC/SERP_BOT/ClaudeChat.

_dashboard_html = None


def _assemble_dashboard() -> str:
    """Assemble dashboard HTML from static files."""
    base = os.path.dirname(os.path.abspath(__file__))
    css_dir = os.path.join(base, "static", "css")
    js_dir = os.path.join(base, "static", "js")

    # Load CSS
    css_parts = []
    if os.path.isdir(css_dir):
        for fname in sorted(os.listdir(css_dir)):
            if fname.endswith(".css"):
                with open(os.path.join(css_dir, fname)) as f:
                    css_parts.append(f"/* {fname} */\n{f.read()}")
    css = "\n".join(css_parts)

    # Load JS (numbered prefix for load order)
    js_parts = []
    if os.path.isdir(js_dir):
        for fname in sorted(os.listdir(js_dir)):
            if fname.endswith(".js"):
                with open(os.path.join(js_dir, fname)) as f:
                    js_parts.append(f"// --- {fname} ---\n{f.read()}")
    js = "\n".join(js_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scope0 - Zero Unnecessary Access</title>
    <style>{css}</style>
</head>
<body>
    <canvas id="bgCanvas"></canvas>
    <div id="app">
        <div id="loginOverlay" class="overlay hidden">
            <div class="overlay-content">
                <h1>Scope0</h1>
                <p>Zero unnecessary access. See what your tokens actually expose.</p>
                <button onclick="window.location.href='/auth/login'" class="btn-login">
                    Sign in with Auth0
                </button>
            </div>
        </div>
        <div id="loadingIndicator" class="loading-indicator hidden">
            <div class="loading-grid"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
            <div>SCANNING<span class="loading-dots"></span></div>
        </div>
        <div id="dashboard" class="hidden">
            <div id="exposurePanel" class="panel panel-left">
                <h2>Exposure</h2>
                <div id="scoreGauge"></div>
                <div class="panel-tabs">
                    <button class="panel-tab active" onclick="switchExposureTab('findings')">Findings</button>
                    <button class="panel-tab" onclick="switchExposureTab('history')">History</button>
                </div>
                <div id="findings" class="tab-content"><div style="color:rgba(0,255,0,0.2);font-size:12px;padding:8px">Waiting for scan results...</div></div>
                <div id="auditTimeline" class="tab-content hidden"><div style="color:rgba(0,255,0,0.2);font-size:12px;padding:8px">No scan history yet</div></div>
            </div>
            <div id="chatPanel" class="panel panel-center">
                <div id="chatHeader">
                    <div style="display:flex;align-items:center;gap:8px">
                        <h2 style="margin:0;padding:0;border:0">Scope0</h2>
                        <div id="connStatus" style="display:flex;align-items:center;gap:6px;margin-left:8px"></div>
                    </div>
                    <div style="display:flex;align-items:center;gap:12px">
                        <div id="userInfo"></div>
                        <button onclick="sessionStorage.removeItem('scope0_thread_id');sendMessage('Scan my connected services.')" style="background:none;border:1px solid rgba(0,255,0,0.15);color:rgba(0,255,0,0.4);font-family:'Courier New',monospace;font-size:11px;padding:4px 10px;cursor:pointer;border-radius:3px">rescan</button>
                        <button id="logoutBtn" onclick="window.location.href='/auth/logout'" style="background:none;border:1px solid rgba(0,255,0,0.15);color:rgba(0,255,0,0.4);font-family:'Courier New',monospace;font-size:11px;padding:4px 10px;cursor:pointer;border-radius:3px">logout</button>
                    </div>
                </div>
                <div id="messages"></div>
                <div id="cibaCard" class="hidden"></div>
                <div id="chatInput">
                    <input type="text" id="messageInput" placeholder="Ask about your exposure, PRs, emails..."
                           autocomplete="off" />
                    <button id="sendBtn" onclick="sendMessage()">Send</button>
                </div>
            </div>
            <div id="controlPanel" class="panel panel-right">
                <h2>Controls</h2>
                <div id="toolToggles"></div>
                <h3>Audit Trail</h3>
                <div id="auditTrail"></div>
                <h3>Scope Utilization</h3>
                <div id="scopeUtil"></div>
            </div>
        </div>
    </div>
    <script>{js}</script>
</body>
</html>"""


async def serve_dashboard(request: web.Request) -> web.Response:
    global _dashboard_html
    if _dashboard_html is None:
        _dashboard_html = _assemble_dashboard()
    return web.Response(text=_dashboard_html, content_type="text/html")


# --- Helper: get authenticated session or 401 ---

async def _get_session_or_401(request: web.Request):
    """Return (session, user_sub) or raise 401."""
    session = await aiohttp_session.get_session(request)
    user_sub = session.get("user_sub")
    if not user_sub:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Not authenticated"}),
            content_type="application/json",
        )
    return session, user_sub


def _build_config(session, thread_id: str) -> dict:
    """Build LangGraph config from session data."""
    return {
        "configurable": {
            "thread_id": thread_id,
            "_credentials": {"refresh_token": session.get("refresh_token", "")},
            "user_id": session.get("user_sub", ""),
        }
    }


# --- SSE streaming helper ---

async def _stream_graph(response: web.StreamResponse, stream, thread_id: str, config: dict = None) -> None:
    """Stream LangGraph astream chunks as SSE events.

    Handles:
    - "messages" mode: AIMessageChunk → event: text
    - "updates" mode: __interrupt__ → event: token_vault_interrupt / ciba_pending
    - "updates" mode: tools → event: tool_result
    - Auto-computes exposure score when both scans complete (deterministic)
    - Auto-disables sendEmail after score (deterministic self-restriction)
    """
    scan_results = {}  # Collect scan results for auto-score computation

    try:
        async for chunk in stream:
            mode = chunk[0]

            if mode == "messages":
                msg, _metadata = chunk[1]
                if isinstance(msg, AIMessageChunk) and msg.content:
                    await response.write(
                        f"event: text\ndata: {json.dumps({'content': msg.content})}\n\n".encode()
                    )

            elif mode == "updates":
                update_data = chunk[1]

                # --- Interrupt detection ---
                if "__interrupt__" in update_data:
                    interrupts = update_data["__interrupt__"]
                    if interrupts:
                        interrupt_obj = interrupts[0]
                        interrupt_value = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj

                        logging.getLogger("scope0").info("Interrupt value: %s", interrupt_value)
                        if Auth0Interrupt.is_interrupt(interrupt_value):
                            code = interrupt_value.get("code", "")

                            if code == "TOKEN_VAULT_ERROR":
                                await response.write(
                                    f"event: token_vault_interrupt\n"
                                    f"data: {json.dumps(interrupt_value)}\n\n".encode()
                                )
                            elif code.startswith("ASYNC_AUTHORIZATION_"):
                                await response.write(
                                    f"event: ciba_pending\n"
                                    f"data: {json.dumps(interrupt_value)}\n\n".encode()
                                )
                            else:
                                await response.write(
                                    f"event: auth0_interrupt\n"
                                    f"data: {json.dumps(interrupt_value)}\n\n".encode()
                                )
                    # After interrupt, stop streaming — frontend handles resume
                    break

                # --- Tool results (for audit trail + exposure updates) ---
                if "tools" in update_data:
                    tool_messages = update_data["tools"].get("messages", [])
                    for tool_msg in tool_messages:
                        if hasattr(tool_msg, "name") and hasattr(tool_msg, "content"):
                            try:
                                result = (
                                    json.loads(tool_msg.content)
                                    if isinstance(tool_msg.content, str)
                                    else tool_msg.content
                                )
                            except (json.JSONDecodeError, TypeError):
                                result = {"raw": str(tool_msg.content)}
                            await response.write(
                                f"event: tool_result\n"
                                f"data: {json.dumps({'tool': tool_msg.name, 'result': result})}\n\n".encode()
                            )

                            # --- Persist to audit store ---
                            if config:
                                _uid = config.get("configurable", {}).get("user_id", "")
                                if tool_msg.name in ("scanGitHubExposure", "scanGoogleExposure", "scanSlackExposure"):
                                    try:
                                        store_scan_result(_uid, tool_msg.name, result if isinstance(result, dict) else {})
                                    except Exception as _ae:
                                        logging.getLogger("scope0").debug("Audit store: %s", _ae)

                            # --- Collect scan results for auto-score ---
                            if tool_msg.name in ("scanGitHubExposure", "scanGoogleExposure", "scanSlackExposure"):
                                scan_results[tool_msg.name] = result if isinstance(result, dict) else {}

                            # --- Auto-compute score + self-restrict when both scans complete ---
                            if tool_msg.name in ("scanGitHubExposure", "scanGoogleExposure"):
                                if "scanGitHubExposure" in scan_results and "scanGoogleExposure" in scan_results:
                                    from lib.exposure_scoring import compute_exposure_score
                                    auto_score = compute_exposure_score(
                                        scan_results.get("scanGitHubExposure", {}),
                                        scan_results.get("scanGoogleExposure", {}),
                                        scan_results.get("scanSlackExposure"),
                                    )
                                    # Send score
                                    await response.write(
                                        f"event: tool_result\n"
                                        f"data: {json.dumps({'tool': 'generateExposureScore', 'result': auto_score})}\n\n".encode()
                                    )
                                    # Persist score + session
                                    if config:
                                        _uid = config.get("configurable", {}).get("user_id", "")
                                        try:
                                            store_exposure_score(_uid, auto_score)
                                        except Exception as _ae:
                                            logging.getLogger("scope0").debug("Audit store: %s", _ae)
                                        try:
                                            save_last_session(_uid, scan_results, auto_score)
                                        except Exception as _ae:
                                            logging.getLogger("scope0").debug("Audit store: %s", _ae)

                                    # Deterministic self-restriction — disable sendEmail IF currently enabled
                                    if config:
                                        try:
                                            user_id = config.get("configurable", {}).get("user_id", "")
                                            if user_id:
                                                is_enabled = await can_use_tool(user_id, "sendEmail")
                                                if is_enabled:
                                                    await set_tool_access(user_id, "sendEmail", False)
                                                    restrict_data = {'disabled': 'sendEmail', 'reason': 'Auto-restricted: not needed for exposure audit', 'note': 'Re-enable in control panel if needed'}
                                                    await response.write(
                                                        f"event: tool_result\n"
                                                        f"data: {json.dumps({'tool': 'disableMyTool', 'result': restrict_data})}\n\n".encode()
                                                    )
                                                    try:
                                                        store_self_restriction(user_id, "sendEmail", restrict_data["reason"])
                                                    except Exception as _ae:
                                                        logging.getLogger("scope0").debug("Audit store: %s", _ae)
                                        except Exception as exc:
                                            logging.getLogger("scope0").warning("Auto self-restrict failed: %s", exc)

    except ConnectionResetError:
        pass  # Client disconnected
    except asyncio.CancelledError:
        pass  # Request cancelled
    except Exception as e:
        error_msg = str(e)
        logging.getLogger("scope0").warning("Stream error: %s", e, exc_info=True)
        try:
            # Rate limit — tell client to retry
            if "429" in error_msg or "ResourceExhausted" in error_msg or "quota" in error_msg.lower():
                await response.write(
                    f"event: error\ndata: {json.dumps({'message': 'Rate limited. Please wait a moment and try again.'})}\n\n".encode()
                )
            else:
                await response.write(
                    f"event: error\ndata: {json.dumps({'message': 'An internal error occurred'})}\n\n".encode()
                )
        except ConnectionResetError:
            pass


# --- Chat endpoint ---

async def chat_handler(request: web.Request) -> web.Response:
    """POST /api/chat — send message, stream response via SSE."""
    session, user_sub = await _get_session_or_401(request)
    data = await request.json()
    message = data.get("message", "").strip()
    if not message:
        return web.json_response({"error": "Message required"}, status=400)

    thread_id = data.get("thread_id") or str(uuid.uuid4())
    config = _build_config(session, thread_id)

    response = web.StreamResponse()
    response.content_type = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    await response.prepare(request)

    # Send thread_id as first event — frontend needs it for resume calls
    await response.write(
        f"event: thread_id\ndata: {json.dumps({'thread_id': thread_id})}\n\n".encode()
    )

    stream = graph.astream(
        {"messages": [HumanMessage(content=message)]},
        stream_mode=["messages", "updates"],
        config=config,
    )

    await _stream_graph(response, stream, thread_id, config)
    return response


# --- Resume endpoint ---

async def resume_handler(request: web.Request) -> web.Response:
    """POST /api/resume — resume after Token Vault connect or CIBA approval."""
    session, user_sub = await _get_session_or_401(request)
    data = await request.json()
    thread_id = data.get("thread_id")
    if not thread_id:
        return web.json_response({"error": "thread_id required"}, status=400)

    config = _build_config(session, thread_id)

    response = web.StreamResponse()
    response.content_type = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    await response.prepare(request)

    # Resume from checkpoint — same pattern as Auth0 example app.py:88
    stream = graph.astream(
        Command(resume=""),
        stream_mode=["messages", "updates"],
        config=config,
    )

    await _stream_graph(response, stream, thread_id, config)
    return response


# --- Tool management endpoints ---

async def list_tools_handler(request: web.Request) -> web.Response:
    """GET /api/tools — list all tools with FGA enabled/disabled status."""
    session, user_sub = await _get_session_or_401(request)
    tool_names = [
        "scanGitHubExposure",
        "scanGoogleExposure",
        "listPullRequests",
        "searchEmails",
        "listCalendarEvents",
        "createIssue",
        "sendEmail",
    ]
    statuses = {}
    for name in tool_names:
        statuses[name] = await can_use_tool(user_sub, name)  # Fail-closed on FGA error
    return web.json_response(statuses)


async def toggle_tool_handler(request: web.Request) -> web.Response:
    """POST /api/tools/toggle — enable or disable a tool via FGA."""
    session, user_sub = await _get_session_or_401(request)
    data = await request.json()
    tool_name = data.get("tool_name")
    enabled = data.get("enabled")
    if not tool_name or enabled is None:
        return web.json_response(
            {"error": "tool_name and enabled required"}, status=400
        )
    try:
        await set_tool_access(user_sub, tool_name, bool(enabled))
    except Exception as exc:
        logging.getLogger("scope0").warning("Tool toggle failed: %s", exc)
        return web.json_response(
            {"error": "Failed to update tool access. FGA service may be unavailable."},
            status=503,
        )
    return web.json_response({"ok": True, "tool": tool_name, "enabled": bool(enabled)})


# --- Session restore endpoint ---

async def session_handler(request: web.Request) -> web.Response:
    """GET /api/session — return last session data for page refresh restore."""
    session, user_sub = await _get_session_or_401(request)
    last = get_last_session(user_sub)
    if not last:
        return web.json_response({"found": False})
    return web.json_response({"found": True, **last})


# --- Timeline endpoint ---

async def timeline_handler(request: web.Request) -> web.Response:
    """GET /api/timeline — return audit timeline for the current user."""
    session, user_sub = await _get_session_or_401(request)
    timeline = get_audit_timeline(user_sub, limit=30)
    return web.json_response(timeline)


# --- Routes ---

app.router.add_get("/", serve_dashboard)
app.router.add_post("/api/chat", chat_handler)
app.router.add_post("/api/resume", resume_handler)
app.router.add_get("/api/tools", list_tools_handler)
app.router.add_get("/api/session", session_handler)
app.router.add_get("/api/timeline", timeline_handler)
app.router.add_post("/api/tools/toggle", toggle_tool_handler)
setup_auth_routes(app)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    web.run_app(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
    )
