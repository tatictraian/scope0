"""List pull requests for the authenticated user's repositories."""

import asyncio

from github import Github, GithubException
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_github
from lib.fga import fga_tool_auth


def _list_pull_requests_sync(repo: str = "", state: str = "open") -> dict:
    """List PRs. If repo is empty, lists PRs across all user repos."""
    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access GitHub")

    g = Github(token)
    prs = []

    try:
        if repo:
            repo_obj = g.get_repo(repo)
            for pr in repo_obj.get_pulls(state=state)[:20]:
                prs.append({
                    "repo": repo,
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "author": pr.user.login if pr.user else "unknown",
                    "created_at": pr.created_at.isoformat() if pr.created_at else "",
                    "updated_at": pr.updated_at.isoformat() if pr.updated_at else "",
                    "html_url": pr.html_url,
                })
        else:
            user = g.get_user()
            for r in list(user.get_repos())[:10]:
                try:
                    for pr in r.get_pulls(state=state)[:5]:
                        prs.append({
                            "repo": r.full_name,
                            "number": pr.number,
                            "title": pr.title,
                            "state": pr.state,
                            "author": pr.user.login if pr.user else "unknown",
                            "created_at": pr.created_at.isoformat() if pr.created_at else "",
                            "updated_at": pr.updated_at.isoformat() if pr.updated_at else "",
                            "html_url": pr.html_url,
                        })
                except GithubException:
                    pass
    except GithubException as e:
        if e.status == 401:
            raise TokenVaultError("Authorization required to access GitHub")
        return {"error": str(e), "prs": []}

    return {"prs": prs, "total": len(prs), "state_filter": state}


@fga_tool_auth("listPullRequests")
async def _list_pull_requests(repo: str = "", state: str = "open") -> dict:
    return await asyncio.to_thread(_list_pull_requests_sync, repo, state)


class ListPullRequestsSchema(BaseModel):
    repo: str = Field(default="", description="Repository in owner/name format. Empty for all repos.")
    state: str = Field(default="open", description="PR state: open, closed, or all")

list_pull_requests_tool = with_github(
    StructuredTool(
        name="listPullRequests",
        description=(
            "List pull requests. Optionally filter by repo (owner/name) and state (open/closed/all). "
            "If no repo specified, lists PRs across all user repos."
        ),
        args_schema=ListPullRequestsSchema,
        coroutine=_list_pull_requests,
    )
)
