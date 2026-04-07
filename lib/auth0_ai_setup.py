"""Auth0 AI wrapper factories for Token Vault and CIBA.

Creates reusable decorators that wrap LangChain StructuredTool objects
with Auth0 Token Vault (OAuth token exchange) and CIBA (human approval).

Import paths verified from auth0-ai-python SDK source:
- Auth0AI: auth0_ai_langchain.auth0_ai (auth0_ai.py:10)
- with_token_vault: Auth0AI method (auth0_ai.py:74)
- with_async_authorization: Auth0AI method (auth0_ai.py:24)
"""

import os

from langchain_core.runnables import ensure_config

from auth0_ai_langchain.auth0_ai import Auth0AI

auth0_ai = Auth0AI()

# --- Token Vault wrappers (one per connection) ---
# Each returns a Callable[[BaseTool], BaseTool] decorator.
# Verified pattern from: examples/calling-apis/langchain-examples/src/auth0/auth0_ai.py

with_github = auth0_ai.with_token_vault(
    connection="github",
    scopes=["repo", "read:user"],
)

with_google = auth0_ai.with_token_vault(
    connection="google-oauth2",
    scopes=[
        "openid",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ],
)

# Slack — optional, may not be available on trial
with_slack = auth0_ai.with_token_vault(
    connection="sign-in-with-slack",
    scopes=["channels:read", "groups:read"],
)

# --- CIBA wrappers (one per approval type) ---
# binding_message receives the tool function's kwargs as positional args.
# user_id resolved per-request from LangGraph's RunnableConfig.
# Verified from: async_authorizer_base.py:112-117 (user_id resolution)
# Verified from: async_authorizer_base.py:124-129 (binding_message resolution)

_ciba_user_id = lambda *_, **__: ensure_config().get("configurable", {}).get("user_id")

with_issue_approval = auth0_ai.with_async_authorization(
    scopes=["openid"],
    audience=os.getenv("AUTH0_AUDIENCE", "https://scope0.local/api"),
    binding_message=lambda repo, title, **_: f'Create GitHub issue in {repo}: "{title}"',
    user_id=_ciba_user_id,
)

with_email_approval = auth0_ai.with_async_authorization(
    scopes=["openid"],
    audience=os.getenv("AUTH0_AUDIENCE", "https://scope0.local/api"),
    binding_message=lambda to, subject, **_: f'Send email to {to}: "{subject}"',
    user_id=_ciba_user_id,
)
