"""List upcoming calendar events."""

import asyncio
from datetime import datetime, timedelta, timezone

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_google
from lib.fga import fga_tool_auth


def _list_calendar_events_sync(days_ahead: int = 7, max_results: int = 20) -> dict:
    """List upcoming calendar events within the specified number of days."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access Google")

    creds = Credentials(token=token)
    days_ahead = min(days_ahead, 30)  # Cap to 30 days
    max_results = min(max_results, 50)  # Cap to 50 events

    try:
        cal = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()

        events_result = (
            cal.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        results = []
        for event in events:
            start = event.get("start", {})
            end = event.get("end", {})
            results.append({
                "summary": event.get("summary", "(no title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": event.get("location", ""),
                "attendees": [
                    a.get("email", "") for a in event.get("attendees", [])
                ],
                "organizer": event.get("organizer", {}).get("email", ""),
                "html_link": event.get("htmlLink", ""),
            })

        return {
            "events": results,
            "total": len(results),
            "range": f"{days_ahead} days from now",
        }
    except HttpError as e:
        if e.resp.status == 401:
            raise TokenVaultError("Authorization required to access Google")
        return {"error": f"Calendar API error: {e.resp.status}", "events": []}


@fga_tool_auth("listCalendarEvents")
async def _list_calendar_events(days_ahead: int = 7, max_results: int = 20) -> dict:
    return await asyncio.to_thread(_list_calendar_events_sync, days_ahead, max_results)


class ListCalendarEventsSchema(BaseModel):
    days_ahead: int = Field(default=7, description="Days ahead to look (max 30)")
    max_results: int = Field(default=20, description="Max events to return (max 50)")

list_calendar_events_tool = with_google(
    StructuredTool(
        name="listCalendarEvents",
        description=(
            "List upcoming calendar events. Optionally specify days_ahead (default 7, max 30) "
            "and max_results (default 20, max 50)."
        ),
        args_schema=ListCalendarEventsSchema,
        coroutine=_list_calendar_events,
    )
)
