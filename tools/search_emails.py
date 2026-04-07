"""Search Gmail for emails matching a query."""

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_google
from lib.fga import fga_tool_auth


def _search_emails_sync(query: str, max_results: int = 10) -> dict:
    """Search Gmail using the standard Gmail search syntax."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access Google")

    creds = Credentials(token=token)
    max_results = min(max_results, 20)  # Cap to avoid excessive API calls

    try:
        gmail = build("gmail", "v1", credentials=creds)
        msg_list = (
            gmail.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = msg_list.get("messages", [])
        results = []
        for msg_summary in messages:
            try:
                msg = (
                    gmail.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_summary["id"],
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject", "Date"],
                    )
                    .execute()
                )
                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                results.append({
                    "id": msg_summary["id"],
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                })
            except HttpError:
                pass  # Skip individual message errors

        return {
            "query": query,
            "total_results": msg_list.get("resultSizeEstimate", 0),
            "emails": results,
        }
    except HttpError as e:
        if e.resp.status == 401:
            raise TokenVaultError("Authorization required to access Google")
        return {"error": f"Gmail API error: {e.resp.status}", "emails": []}


@fga_tool_auth("searchEmails")
async def _search_emails(query: str, max_results: int = 10) -> dict:
    return await asyncio.to_thread(_search_emails_sync, query, max_results)


class SearchEmailsSchema(BaseModel):
    query: str = Field(description="Gmail search query (standard Gmail syntax)")
    max_results: int = Field(default=10, description="Max results to return (max 20)")

search_emails_tool = with_google(
    StructuredTool(
        name="searchEmails",
        description=(
            "Search Gmail using standard Gmail search syntax. Returns email metadata "
            "(from, to, subject, date, snippet). No email body is read."
        ),
        args_schema=SearchEmailsSchema,
        coroutine=_search_emails,
    )
)
