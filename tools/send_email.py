"""Send an email via Gmail — requires Token Vault + CIBA approval + FGA.

Same wrapping order as create_issue:
FGA → StructuredTool → CIBA → Token Vault
"""

import asyncio
import base64
from email.mime.text import MIMEText

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_email_approval, with_google
from lib.fga import fga_tool_auth


def _send_email_sync(to: str, subject: str, body: str) -> dict:
    """Send an email via Gmail API."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access Google")

    creds = Credentials(token=token)

    try:
        gmail = build("gmail", "v1", credentials=creds)
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            gmail.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return {
            "sent": True,
            "message_id": sent.get("id", ""),
            "to": to,
            "subject": subject,
        }
    except HttpError as e:
        if e.resp.status == 401:
            raise TokenVaultError("Authorization required to access Google")
        return {"sent": False, "error": f"Gmail API error: {e.resp.status}"}


@fga_tool_auth("sendEmail")
async def _send_email(to: str, subject: str, body: str) -> dict:
    return await asyncio.to_thread(_send_email_sync, to, subject, body)


class SendEmailSchema(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body text")

send_email_tool = with_google(
    with_email_approval(
        StructuredTool(
            name="sendEmail",
            description="Send an email via Gmail. Requires CIBA approval on your phone.",
            args_schema=SendEmailSchema,
            coroutine=_send_email,
        )
    )
)
