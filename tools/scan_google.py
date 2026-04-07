"""Google exposure scanner — Gmail profile + thread count, Calendar events,
correspondent mapping, scope analysis.

Uses google-api-python-client (synchronous) wrapped in asyncio.to_thread.
"""

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_google
from lib.fga import fga_tool_auth


def _scan_google_exposure_sync() -> dict:
    """Synchronous scan — runs in a thread via asyncio.to_thread."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access Google")

    creds = Credentials(token=token)
    results = {}

    # --- GMAIL PROFILE ---
    try:
        gmail = build("gmail", "v1", credentials=creds)
        profile = gmail.users().getProfile(userId="me").execute()
        results["email"] = {
            "address": profile.get("emailAddress", ""),
            "totalMessages": profile.get("messagesTotal", 0),
            "totalThreads": profile.get("threadsTotal", 0),
        }
    except HttpError as e:
        results["email"] = {
            "error": f"Gmail API error: {e.resp.status}",
            "totalThreads": 0,
        }

    # --- GMAIL CORRESPONDENT MAP (metadata only, no body) ---
    try:
        gmail = build("gmail", "v1", credentials=creds)
        msg_list = (
            gmail.users()
            .messages()
            .list(userId="me", maxResults=50, q="newer_than:30d")
            .execute()
        )
        correspondents = {}
        messages = msg_list.get("messages", [])
        for msg_summary in messages[:50]:
            try:
                msg = (
                    gmail.users()
                    .messages()
                    .get(userId="me", id=msg_summary["id"], format="metadata",
                         metadataHeaders=["From", "To"])
                    .execute()
                )
                for header in msg.get("payload", {}).get("headers", []):
                    if header["name"] in ("From", "To"):
                        raw = header["value"]
                        # Extract email from "Display Name <email@example.com>" format
                        import re as _re
                        match = _re.search(r'<([^>]+)>', raw)
                        addr = match.group(1).lower() if match else raw.strip().lower()
                        correspondents[addr] = correspondents.get(addr, 0) + 1
            except HttpError:
                pass  # Skip individual message errors
        # Top 10 correspondents
        top = sorted(correspondents.items(), key=lambda x: x[1], reverse=True)[:10]
        results["correspondents"] = {
            "top": [{"address": addr, "count": count} for addr, count in top],
            "total_unique": len(correspondents),
        }
    except HttpError as e:
        results["correspondents"] = {"error": f"Gmail API error: {e.resp.status}"}

    # --- CALENDAR EVENTS ---
    try:
        from datetime import datetime, timezone, timedelta

        cal = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=30)).isoformat()
        events_result = (
            cal.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        # Attendee frequency
        attendee_freq = {}
        for event in events:
            for attendee in event.get("attendees", []):
                email = attendee.get("email", "")
                if email:
                    attendee_freq[email] = attendee_freq.get(email, 0) + 1

        top_attendees = sorted(
            attendee_freq.items(), key=lambda x: x[1], reverse=True
        )[:10]

        results["calendar"] = {
            "upcomingEvents": len(events),
            "timeRange": f"{time_min} to {time_max}",
            "topAttendees": [
                {"email": email, "count": count} for email, count in top_attendees
            ],
        }
    except HttpError as e:
        results["calendar"] = {
            "error": f"Calendar API error: {e.resp.status}",
            "upcomingEvents": 0,
        }

    # --- SCOPE ANALYSIS ---
    # Compute overprivilege from configured scopes vs what tools need
    granted_scopes = [
        {"scope": "gmail.readonly", "permits": "Read all emails, attachments, labels, drafts"},
        {"scope": "gmail.send", "permits": "Send emails on behalf of user"},
        {"scope": "calendar.events.readonly", "permits": "Read all calendar events, attendees, locations"},
    ]
    # Our scan tools only need metadata-level read access
    needed_for_scan = {"gmail.readonly", "calendar.events.readonly"}
    # Write tools need send
    needed_for_remediation = {"gmail.send"}
    all_needed = needed_for_scan | needed_for_remediation
    granted_set = {s["scope"] for s in granted_scopes}
    unnecessary = granted_set - all_needed
    # Also flag scope downgrade opportunities
    downgrade_opportunities = [
        {"from": "gmail.readonly", "to": "gmail.metadata", "reason": "Scan reads headers (From/To) only, not email bodies"},
    ]
    # Overprivilege = unnecessary scopes + scopes that could be downgraded
    overprivilege_pct = round((len(unnecessary) + len(downgrade_opportunities)) / (len(granted_set) + len(downgrade_opportunities)) * 100) if granted_set else 0

    results["scope_analysis"] = {
        "granted": granted_scopes,
        "needed_for_scan": list(needed_for_scan),
        "needed_for_remediation": list(needed_for_remediation),
        "unnecessary": list(unnecessary),
        "downgrade_opportunities": downgrade_opportunities,
        "overprivilege_pct": overprivilege_pct,
        "cross_service_note": (
            "Combined with GitHub commit data, your full schedule, "
            "correspondents, and timezone are reconstructable"
        ),
    }

    return results


@fga_tool_auth("scanGoogleExposure")
async def _scan_google_exposure() -> dict:
    """Async wrapper: FGA check (async) + sync scan in thread."""
    return await asyncio.to_thread(_scan_google_exposure_sync)


class ScanGoogleExposureSchema(BaseModel):
    pass

scan_google_exposure_tool = with_google(
    StructuredTool(
        name="scanGoogleExposure",
        args_schema=ScanGoogleExposureSchema,
        description=(
            "Scan Google for exposure: Gmail profile, thread counts, "
            "correspondent map, calendar events, attendee frequency, scope analysis"
        ),
        coroutine=_scan_google_exposure,
    )
)
