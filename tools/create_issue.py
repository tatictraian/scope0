"""Create a GitHub issue — requires Token Vault + CIBA approval + FGA.

Wrapping order (verified from SDK source):
1. FGA decorates raw function (fga_authorizer.py:82 expects Callable)
2. StructuredTool wraps the FGA-decorated function
3. CIBA wraps the StructuredTool (with_issue_approval)
4. Token Vault wraps outermost (with_github)

Execution order at runtime:
1. Token Vault: exchanges refresh token for GitHub access token
2. CIBA: sends Guardian push, waits for user approval
3. StructuredTool: calls _create_issue(**args)
4. FGA: checks OpenFgaClient.check() — if denied, returns message
5. If authorized: function body executes with Token Vault access token
"""

import asyncio

from github import Github, GithubException
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_github, with_issue_approval
from lib.fga import fga_tool_auth


def _create_issue_sync(repo: str, title: str, body: str = "") -> dict:
    """Create a GitHub issue in the specified repo."""
    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access GitHub")

    try:
        g = Github(token)
        repo_obj = g.get_repo(repo)
        issue = repo_obj.create_issue(title=title, body=body)
        return {
            "created": True,
            "number": issue.number,
            "url": issue.html_url,
            "repo": repo,
            "title": title,
        }
    except GithubException as e:
        if e.status == 401:
            raise TokenVaultError("Authorization required to access GitHub")
        return {"created": False, "error": str(e)}


@fga_tool_auth("createIssue")
async def _create_issue(repo: str, title: str, body: str = "") -> dict:
    return await asyncio.to_thread(_create_issue_sync, repo, title, body)


class CreateIssueSchema(BaseModel):
    repo: str = Field(description="Repository in owner/name format")
    title: str = Field(description="Issue title")
    body: str = Field(default="", description="Issue body (markdown)")

create_issue_tool = with_github(
    with_issue_approval(
        StructuredTool(
            name="createIssue",
            description="Create a GitHub issue for remediation tracking. Requires CIBA approval.",
            args_schema=CreateIssueSchema,
            coroutine=_create_issue,
        )
    )
)
