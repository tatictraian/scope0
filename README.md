# Scope0 — Zero Unnecessary Access

AI agent that reveals what your OAuth tokens actually expose, then helps you fix it.

Connects to GitHub and Google via Auth0 Token Vault, scans for secrets, PII, overprivilege, and work patterns, computes a transparent exposure score, offers CIBA-approved remediation, then voluntarily disables its own unused capabilities via FGA.

Uses all three Auth0 AI products: **Token Vault + CIBA + FGA**.

## What It Does

1. **Connect** — Auth0 login, connect GitHub and Google via Token Vault popups
2. **Reveal** — Agent proactively scans connected services:
   - Reads GitHub's built-in secret scanning alerts (200+ patterns)
   - Detects PII (emails) in public commit metadata
   - Analyzes work patterns (timezone, schedule, vacation gaps)
   - Maps Gmail correspondents and calendar attendees
   - Computes transparent exposure score (0-100) with component breakdown
3. **Cross-Reference** — Correlates across services:
   - Same email in GitHub commits + Google = identity bridge
   - Commit timestamps + calendar events = full schedule reconstruction
4. **Remediate** — CIBA-gated actions:
   - Creates GitHub issues for secret rotation, noreply email config, scope downgrade
   - Each write action requires MFA approval (Guardian push on Enterprise, OTP/Email on Pro/trial)
5. **Self-Restrict** — Agent disables its own unused write tools via FGA
   - One-directional: can disable, cannot re-enable
   - Re-enabling requires user action in the control panel

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent | LangGraph (StateGraph + ToolNode + MemorySaver) |
| LLM | Configurable: Gemini 2.5 Flash (default, free), GPT-4o, Claude, Gemma 4 via Ollama |
| Auth | auth0-ai-langchain (Token Vault + CIBA wrappers) |
| Authorization | OpenFGA via auth0-ai (tool-level FGA) |
| Server | Python 3.12 + aiohttp |
| Frontend | Vanilla JS + Canvas 2D |
| APIs | PyGithub, google-api-python-client, httpx |

## Prerequisites

- Python 3.12+
- Auth0 account (free trial includes Token Vault, CIBA, FGA)
- LLM API key — one of:
  - Google AI Studio key (free at ai.google.dev — default, Gemini 2.5 Flash)
  - OpenAI key (GPT-4o, paid)
  - Anthropic key (Claude, paid)
  - Or run Gemma 4 locally via Ollama (free, no API key)
- FGA store at [dashboard.fga.dev](https://dashboard.fga.dev)
- GitHub OAuth App (for Token Vault connection)
- Google Cloud OAuth Client (for Token Vault connection)

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd scope0
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Auth0 Dashboard

**Application** (Regular Web Application, name: "Scope0"):

| Setting | Value |
|---------|-------|
| Allowed Callback URLs | `http://localhost:8080/auth/callback, http://localhost:8080/auth/connect/callback` |
| Allowed Logout URLs | `http://localhost:8080` |
| Allowed Web Origins | `http://localhost:8080` |
| Allowed Origins (CORS) | `http://localhost:8080` |
| Refresh Token Rotation | ON |

**Grant Types** (Settings → Advanced → Grant Types):
- Authorization Code
- Refresh Token
- Client Credentials
- Token Vault (`urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token`)
- CIBA (`urn:openid:params:grant-type:ciba`)

**API Resource** (APIs → Create):
- Identifier: `https://scope0.local/api`
- Signing: RS256

**MRRT** (Applications → Scope0 → Settings → Multi-Resource Refresh Token):
- Enable for the Scope0 API

**Social Connections** (Authentication → Social):

GitHub (`github`):
- Purpose: Authentication and Connected Accounts for Token Vault
- Requires your own GitHub OAuth App (Settings → Developer settings → OAuth Apps)
- Callback URL for GitHub OAuth App: `https://<tenant>.auth0.com/login/callback`
- Scopes: Basic Profile, Email, `read:user`, `repo`

Google (`google-oauth2`):
- Purpose: Authentication and Connected Accounts for Token Vault
- Requires your own Google Cloud OAuth Client (console.cloud.google.com)
- Type: Web application
- Redirect URI for Google OAuth Client: `https://<tenant>.auth0.com/login/callback`
- Scopes: Offline Access, Basic Profile, Email, Extended Profile, Calendar.Events.ReadOnly, Gmail.Readonly, Gmail.Send
- Google Cloud: enable Gmail API and Google Calendar API in APIs & Services → Library
- Google Cloud: add your test email in OAuth consent screen → Test users

**CIBA** (Security → Multi-Factor Authentication):
- Enable at least one MFA factor:
  - Push via Auth0 Guardian (Enterprise plan)
  - One-time Password (Pro plan / trial)
  - Email verification (Pro plan / trial)
- Set MFA policy to "Always"
- Enroll your test user on next login
- Note: CIBA implementation is complete. Guardian push requires Enterprise. OTP/Email work on trial.

### 3. FGA Setup

1. Sign up at [dashboard.fga.dev](https://dashboard.fga.dev)
2. Create a new store
3. Go to Settings → note `FGA_STORE_ID`
4. Create API credentials → note `FGA_CLIENT_ID` and `FGA_CLIENT_SECRET`

### 4. Environment Variables

```bash
cp .env.example .env
```

Fill in all values:
- `AUTH0_DOMAIN` — your tenant (e.g., `dev-xxxxx.us.auth0.com`)
- `AUTH0_CLIENT_ID` / `AUTH0_CLIENT_SECRET` — from the Scope0 application
- `AUTH0_AUDIENCE` — `https://scope0.local/api`
- `SESSION_SECRET` — generate with `openssl rand -hex 32`
- `FGA_STORE_ID` / `FGA_CLIENT_ID` / `FGA_CLIENT_SECRET` — from dashboard.fga.dev
- `GOOGLE_API_KEY` — from ai.google.dev (default LLM: Gemini 2.5 Flash, free tier)
- Or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` if using alternative providers

### 5. Initialize FGA Model

```bash
source venv/bin/activate
python scripts/fga_init.py <your-auth0-user-sub>
```

The user sub is the Auth0 user ID (e.g., `auth0|abc123`). Find it in Auth0 Dashboard → User Management → Users.

This writes the authorization model (with tool categories) and seeds default tuples: read tools enabled, write tools disabled.

### 6. Run

```bash
source venv/bin/activate
python api_server.py
```

Open http://localhost:8080

## How Auth0 AI Products Are Used

### Token Vault
Each tool that accesses an external API is wrapped with `auth0_ai.with_token_vault(connection=..., scopes=[...])`. When the tool runs and no token is available, a `GraphInterrupt` fires. The backend sends an SSE event to the frontend, which opens a popup for the user to authorize. After authorization, the frontend calls `/api/resume` and the agent continues from its checkpoint.

### CIBA
Write tools (`createIssue`, `sendEmail`) are wrapped with `auth0_ai.with_async_authorization(binding_message=..., user_id=...)`. When called, Auth0 sends an MFA challenge to the user (Guardian push on Enterprise, OTP/Email on trial). The `binding_message` shows exactly what the agent wants to do (e.g., "Create GitHub issue in repo: title"). The frontend polls `/api/resume` every 5 seconds until the user approves or the request times out (5 minutes).

### FGA
Every API tool's raw function is decorated with `fga_tool_auth(tool_name)` which checks `user:can_use:tool` in OpenFGA before execution. The dashboard has per-tool toggles and category-level toggles (read_tools, write_tools). The agent can call `disableMyTool` to delete its own FGA tuple — one-directional, no re-enable path exists.

## Project Structure

```
scope0/
├── api_server.py              # aiohttp app, dashboard assembly, SSE streaming
├── lib/
│   ├── agent.py               # LangGraph StateGraph + ToolNode + MemorySaver
│   ├── auth0_ai_setup.py      # Token Vault + CIBA wrapper factories
│   ├── auth0_web.py           # OAuth login/callback/connect handlers
│   ├── exposure_scoring.py    # Transparent exposure score computation
│   ├── fga.py                 # FGA authorizer + can_use_tool + set_tool_access
│   └── audit_store.py         # SQLite persistence for scan history + timeline
├── tools/
│   ├── scan_github.py         # GitHub exposure scanner (Token Vault + FGA)
│   ├── scan_google.py         # Google exposure scanner (Token Vault + FGA)
│   ├── scan_slack.py          # Slack exposure scanner (Token Vault + FGA)
│   ├── list_prs.py            # List pull requests (Token Vault + FGA)
│   ├── search_emails.py       # Search Gmail (Token Vault + FGA)
│   ├── list_events.py         # List calendar events (Token Vault + FGA)
│   ├── list_channels.py       # List Slack channels (Token Vault + FGA)
│   ├── create_issue.py        # Create GitHub issue (Token Vault + CIBA + FGA)
│   ├── send_email.py          # Send email (Token Vault + CIBA + FGA)
│   ├── generate_score.py      # Compute exposure score (pure computation)
│   ├── analyze_session.py     # Session scope analysis (pure computation)
│   └── self_restrict.py       # Agent self-restriction via FGA
├── static/
│   ├── css/dashboard.css
│   └── js/
│       ├── 00_canvas.js       # Reactive canvas background
│       ├── 01_globals.js      # State, API helpers
│       ├── 02_realtime.js     # SSE streaming, interrupt handlers
│       ├── 03_exposure.js     # Exposure gauge, findings
│       ├── 04_chat.js         # Chat, CIBA approval cards
│       ├── 05_controls.js     # Tool toggles, audit trail, scope bars
│       └── 06_init.js         # Startup, login check
├── scripts/
│   └── fga_init.py            # FGA model + seed tuples
├── tests.py                   # Smoke tests (28 tests)
├── BLOG_POST.md               # Hackathon bonus blog post
├── LICENSE                    # MIT
├── requirements.txt
└── .env.example
```

## Architecture Notes

- LangGraph `astream(stream_mode=["messages", "updates"])` gives real-time token streaming AND interrupt detection in one call
- Audit timeline persisted in SQLite (`lib/audit_store.py`) — scan results, scores, self-restriction events survive restarts
- Interrupts surface as `__interrupt__` in update chunks, not raised as exceptions
- Resume via `Command(resume='')` — same pattern as Auth0's example app
- FGA wraps raw functions (not StructuredTool objects) — `fga_authorizer.py` expects `Callable`
- `asyncio.to_thread` for synchronous PyGithub/Google API calls — prevents event loop blocking
- `handle_tool_errors=False` on ToolNode — required for GraphInterrupt propagation
- LLM is configurable via `LLM_PROVIDER` + `LLM_MODEL` env vars (default: Gemini 2.5 Flash)

## License

MIT
