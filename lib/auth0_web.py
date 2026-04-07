"""Auth0 OAuth 2.0 web flow handlers for aiohttp.

Provides:
- /auth/login: redirect to Auth0 Universal Login
- /auth/callback: exchange code for tokens, store refresh_token + user_sub in session
- /auth/connect/{connection}: redirect to Auth0 for Token Vault connected account
- /auth/connect/callback: exchange code, close popup
- /auth/logout: clear session, redirect to Auth0 logout
- /auth/me: return current user info from session

Verified patterns:
- Auth0 example uses auth0-fastapi's register_auth_routes (app.py:34)
- We replicate the same OAuth2 flow manually for aiohttp compatibility
- Connect flow adds connection + prompt=consent params (verified from
  auth0-fastapi source and JS SDK's connectAccountWithRedirect)
- Refresh token required for Token Vault (offline_access scope)
"""

import base64
import hashlib
import html as html_module
import json
import os
import secrets
from urllib.parse import urlencode

import aiohttp_session
import httpx
from aiohttp import web

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID", "")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET", "")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8080")


async def login_handler(request: web.Request) -> web.Response:
    """Redirect to Auth0 Universal Login with CSRF-safe state parameter."""
    state = secrets.token_urlsafe(32)
    session = await aiohttp_session.get_session(request)
    session["oauth_state"] = state
    params = {
        "client_id": AUTH0_CLIENT_ID,
        "redirect_uri": f"{APP_BASE_URL}/auth/callback",
        "response_type": "code",
        "scope": "openid profile email offline_access",
        "audience": AUTH0_AUDIENCE,
        "state": state,
    }
    url = f"https://{AUTH0_DOMAIN}/authorize?{urlencode(params)}"
    return web.HTTPFound(url)


async def callback_handler(request: web.Request) -> web.Response:
    """Exchange authorization code for tokens and store in session."""
    # Validate OAuth state parameter (CSRF protection)
    session = await aiohttp_session.get_session(request)
    expected_state = session.pop("oauth_state", None)
    received_state = request.query.get("state")
    if not expected_state or expected_state != received_state:
        return web.Response(text="Invalid state parameter — possible CSRF attack", status=403)

    code = request.query.get("code")
    if not code:
        return web.Response(text="Missing code parameter", status=400)

    error = request.query.get("error")
    if error:
        desc = request.query.get("error_description", error)
        return web.Response(text=f"Auth0 error: {desc}", status=400)

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{APP_BASE_URL}/auth/callback",
            },
        )

    if token_resp.status_code != 200:
        return web.Response(
            text=f"Token exchange failed: {token_resp.status_code}",
            status=502,
        )

    tokens = token_resp.json()

    if "refresh_token" not in tokens:
        return web.Response(
            text="No refresh token returned. Verify offline_access scope and "
            "refresh token rotation settings in Auth0 dashboard.",
            status=502,
        )

    # Decode user sub from ID token (base64url, no verification needed — trust Auth0)
    id_token = tokens.get("id_token", "")
    if not id_token:
        return web.Response(text="No id_token returned", status=502)

    try:
        payload_b64 = id_token.split(".")[1]
        # Pad base64url to standard base64
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        user_sub = payload["sub"]
    except (IndexError, KeyError, json.JSONDecodeError, ValueError) as exc:
        return web.Response(text=f"Failed to decode id_token: {exc}", status=502)

    # Store in session — only refresh_token (not access_token, saves cookie space)
    session = await aiohttp_session.get_session(request)
    session["refresh_token"] = tokens["refresh_token"]
    session["user_sub"] = user_sub
    session["user_name"] = payload.get("name", "")
    session["user_email"] = payload.get("email", "")
    session["user_picture"] = payload.get("picture", "")

    return web.HTTPFound("/")


def _generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


async def _get_my_account_token(refresh_token: str) -> str:
    """Exchange refresh token for My Account API access token via MRRT.

    Uses grant_type=refresh_token with audience=https://{domain}/me/
    and scope=create:me:connected_accounts.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": AUTH0_CLIENT_ID,
                "client_secret": AUTH0_CLIENT_SECRET,
                "audience": f"https://{AUTH0_DOMAIN}/me/",
                "scope": "create:me:connected_accounts",
            },
        )
        if resp.status_code != 200:
            raise ValueError(f"Failed to get My Account token: {resp.status_code} {resp.text}")
        return resp.json()["access_token"]


# Connection scopes for Token Vault
CONNECT_SCOPES = {
    "github": ["repo", "read:user"],
    "google-oauth2": [
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ],
    "sign-in-with-slack": ["channels:read", "groups:read"],
}


async def connect_handler(request: web.Request) -> web.Response:
    """Initiate Token Vault Connected Account flow via My Account API.

    Uses the My Account API (not /authorize) to properly register the
    connection in Token Vault. Flow:
    1. Get My Account API access token (MRRT)
    2. POST /me/v1/connected-accounts/connect
    3. Redirect user to connect_uri with ticket
    """
    connection = request.match_info["connection"]
    if connection not in CONNECT_SCOPES:
        return web.Response(text="Unknown connection", status=400)

    session = await aiohttp_session.get_session(request)
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return web.Response(text="Not authenticated", status=401)

    # PKCE
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    try:
        # Get My Account API access token
        ma_token = await _get_my_account_token(refresh_token)

        # Call My Account API to initiate connected account flow
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts/connect",
                json={
                    "connection": connection,
                    "scopes": CONNECT_SCOPES[connection],
                    "redirect_uri": f"{APP_BASE_URL}/auth/connect/callback",
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "state": state,
                },
                headers={"Authorization": f"Bearer {ma_token}"},
            )
            if resp.status_code != 201:
                error_detail = html_module.escape(resp.text[:200])
                return web.Response(
                    text=f"<html><body><p>Connect failed: {error_detail}</p></body></html>",
                    content_type="text/html",
                )
            data = resp.json()

    except Exception as exc:
        error_msg = html_module.escape(str(exc)[:200])
        return web.Response(
            text=f"<html><body><p>Connect error: {error_msg}</p></body></html>",
            content_type="text/html",
        )

    # Store transaction data for the callback
    session["connect_state"] = state
    session["connect_verifier"] = code_verifier
    session["connect_auth_session"] = data.get("auth_session", "")

    # Redirect to the connect URI with ticket
    connect_uri = data.get("connect_uri", "")
    ticket = data.get("connect_params", {}).get("ticket", "")
    redirect_url = f"{connect_uri}?{urlencode({'ticket': ticket})}" if ticket else connect_uri
    return web.HTTPFound(redirect_url)


async def connect_callback_handler(request: web.Request) -> web.Response:
    """Complete the Token Vault Connected Account flow via My Account API.

    Receives connect_code from the callback, exchanges it via
    POST /me/v1/connected-accounts/complete.
    """
    session = await aiohttp_session.get_session(request)

    # Validate state
    expected_state = session.pop("connect_state", None)
    received_state = request.query.get("state")
    if not expected_state or expected_state != received_state:
        return web.Response(
            text="<html><body><p>Invalid state</p><p><a href='javascript:window.close()'>Close</a></p></body></html>",
            content_type="text/html",
        )

    error = request.query.get("error")
    if error:
        desc = html_module.escape(request.query.get("error_description", error))
        return web.Response(
            text=f"<html><body><p>Connection failed: {desc}</p><p><a href='javascript:window.close()'>Close</a></p></body></html>",
            content_type="text/html",
        )

    connect_code = request.query.get("connect_code")
    if not connect_code:
        return web.Response(
            text="<html><body><p>Missing connect_code</p><p><a href='javascript:window.close()'>Close</a></p></body></html>",
            content_type="text/html",
        )

    code_verifier = session.pop("connect_verifier", "")
    auth_session = session.pop("connect_auth_session", "")
    refresh_token = session.get("refresh_token")

    try:
        # Get My Account API access token
        ma_token = await _get_my_account_token(refresh_token)

        # Complete the connected account flow
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://{AUTH0_DOMAIN}/me/v1/connected-accounts/complete",
                json={
                    "auth_session": auth_session,
                    "connect_code": connect_code,
                    "redirect_uri": f"{APP_BASE_URL}/auth/connect/callback",
                    "code_verifier": code_verifier,
                },
                headers={"Authorization": f"Bearer {ma_token}"},
            )
            if resp.status_code != 201:
                error_detail = html_module.escape(resp.text[:200])
                return web.Response(
                    text=f"<html><body><p>Complete failed: {error_detail}</p><p><a href='javascript:window.close()'>Close</a></p></body></html>",
                    content_type="text/html",
                )
    except Exception as exc:
        error_msg = html_module.escape(str(exc)[:200])
        return web.Response(
            text=f"<html><body><p>Complete error: {error_msg}</p><p><a href='javascript:window.close()'>Close</a></p></body></html>",
            content_type="text/html",
        )

    # Close popup
    return web.Response(
        text="<html><body><script>window.close();</script><p>Connected. You can close this window.</p></body></html>",
        content_type="text/html",
    )


async def logout_handler(request: web.Request) -> web.Response:
    """Clear session and redirect to Auth0 logout."""
    session = await aiohttp_session.get_session(request)
    session.invalidate()
    params = {
        "client_id": AUTH0_CLIENT_ID,
        "returnTo": APP_BASE_URL,
    }
    url = f"https://{AUTH0_DOMAIN}/v2/logout?{urlencode(params)}"
    return web.HTTPFound(url)


async def me_handler(request: web.Request) -> web.Response:
    """Return current user info from session (for frontend)."""
    session = await aiohttp_session.get_session(request)
    user_sub = session.get("user_sub")
    if not user_sub:
        return web.json_response({"authenticated": False}, status=401)
    return web.json_response({
        "authenticated": True,
        "sub": user_sub,
        "name": session.get("user_name", ""),
        "email": session.get("user_email", ""),
        "picture": session.get("user_picture", ""),
    })


def setup_auth_routes(app: web.Application) -> None:
    """Register all auth routes on the aiohttp app."""
    app.router.add_get("/auth/login", login_handler)
    app.router.add_get("/auth/callback", callback_handler)
    app.router.add_get("/auth/connect/{connection}", connect_handler)
    app.router.add_get("/auth/connect/callback", connect_callback_handler)
    app.router.add_get("/auth/logout", logout_handler)
    app.router.add_get("/auth/me", me_handler)
