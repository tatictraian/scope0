"""GitHub exposure scanner — reads GitHub's built-in secret scanning alerts,
detects PII in commits, analyzes work patterns, assesses scope overprivilege.

Uses PyGithub (synchronous) + httpx (synchronous) wrapped in asyncio.to_thread
to avoid blocking the aiohttp event loop. contextvars are automatically copied
to the thread (Python 3.12+).

Verified from SDK source:
- get_access_token_from_token_vault() reads from contextvars (token_vault_authorizer.py:13-14)
- TokenVaultError triggers re-auth flow (token_vault_interrupt.py:51-58)
"""

import asyncio

import httpx
from github import Github, GithubException
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from auth0_ai_langchain.token_vault import (
    TokenVaultError,
    get_access_token_from_token_vault,
)
from lib.auth0_ai_setup import with_github
from lib.fga import fga_tool_auth


def _scan_github_exposure_sync() -> dict:
    """Synchronous scan — runs in a thread via asyncio.to_thread."""
    token = get_access_token_from_token_vault()
    if not token:
        raise TokenVaultError("Authorization required to access GitHub")

    g = Github(token)
    results = {}
    repos = []

    # --- REPO INVENTORY ---
    try:
        user = g.get_user()
        repos = list(user.get_repos())
        results["repos"] = {
            "total": len(repos),
            "public": sum(1 for r in repos if not r.private),
            "private": sum(1 for r in repos if r.private),
        }
    except GithubException as e:
        results["repos"] = {"error": str(e), "total": 0, "public": 0, "private": 0}

    # --- SECRET SCANNING: read GitHub's built-in alerts (200+ patterns) ---
    # We READ existing alerts via REST API — no duplication, no rate limit issues.
    # Requires repo scope. Works on public repos automatically.
    secrets_found = []
    for repo in repos[:10]:
        try:
            resp = httpx.get(
                f"https://api.github.com/repos/{repo.full_name}/secret-scanning/alerts",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"state": "open", "per_page": 10},
                timeout=10.0,
            )
            if resp.status_code == 200:
                for alert in resp.json():
                    secrets_found.append({
                        "repo": repo.full_name,
                        "secret_type": alert.get(
                            "secret_type_display_name",
                            alert.get("secret_type", "unknown"),
                        ),
                        "state": alert.get("state", "open"),
                        "created_at": alert.get("created_at", ""),
                        "severity": "CRITICAL",
                        "html_url": alert.get("html_url", ""),
                    })
            # 404 = secret scanning not enabled on this repo — skip silently
        except httpx.HTTPError:
            pass  # Network error on this repo — continue with others

    results["secrets"] = {
        "alerts": secrets_found,
        "total_repos_scanned": min(len(repos), 10),
        "source": "GitHub built-in secret scanning (200+ patterns)",
    }

    # --- PII: email in commit metadata ---
    try:
        emails_found = set()
        for repo in repos[:5]:
            if not repo.private:
                try:
                    for commit in repo.get_commits()[:10]:
                        email = commit.commit.author.email
                        if email and not email.endswith("noreply.github.com"):
                            emails_found.add(email)
                except GithubException:
                    pass  # Empty repo or other issue
        results["email_exposure"] = {
            "emails": list(emails_found),
            "public_repos_checked": sum(1 for r in repos[:5] if not r.private),
            "cross_service_note": (
                "Cross-reference these with your Auth0 profile email "
                "to detect identity bridges across connected services"
            ),
        }
    except GithubException as e:
        results["email_exposure"] = {"error": str(e), "emails": []}

    # --- WORK PATTERN: commit timestamps ---
    try:
        hours = {}
        days_active = set()
        all_dates = []
        for repo in repos[:3]:
            try:
                for commit in repo.get_commits()[:30]:
                    dt = commit.commit.author.date
                    h = dt.hour
                    hours[h] = hours.get(h, 0) + 1
                    days_active.add(dt.strftime("%A"))
                    all_dates.append(dt)
            except GithubException:
                pass  # Empty repo

        peak_hour = max(hours, key=hours.get) if hours else None

        # Activity window analysis — find likely sleep gap and active hours
        inferred_utc_offset = None
        active_window = None
        if hours and sum(hours.values()) >= 5:
            active_hours_list = sorted(hours.keys())
            if len(active_hours_list) >= 3:
                # Find longest gap (likely sleep/offline period)
                max_gap = 0
                gap_after = 0
                for i in range(len(active_hours_list)):
                    next_i = (i + 1) % len(active_hours_list)
                    gap = (active_hours_list[next_i] - active_hours_list[i]) % 24
                    if gap > max_gap:
                        max_gap = gap
                        gap_after = active_hours_list[next_i]  # activity resumes here
                # Only infer timezone if the longest gap is at least 6 hours
                # (shorter gaps aren't sleep, just brief inactivity)
                if max_gap >= 6:
                    gap_before_idx = (active_hours_list.index(gap_after) - 1) % len(active_hours_list)
                    active_start = gap_after
                    active_end = active_hours_list[gap_before_idx]
                    active_window = {
                        "start_utc": active_start,
                        "end_utc": active_end,
                        "sleep_gap_hours": max_gap,
                    }
                    # Best-effort timezone: assume center of active window = 13:00 local
                    if active_end >= active_start:
                        center = (active_start + active_end) / 2
                    else:
                        center = ((active_start + active_end + 24) / 2) % 24
                    inferred_utc_offset = round(13 - center)
                    if inferred_utc_offset > 12:
                        inferred_utc_offset -= 24
                    elif inferred_utc_offset < -12:
                        inferred_utc_offset += 24

        vacation_gaps = []
        if all_dates:
            sorted_dates = sorted(all_dates)
            for i in range(1, len(sorted_dates)):
                gap = (sorted_dates[i] - sorted_dates[i - 1]).days
                if gap > 5:
                    vacation_gaps.append({
                        "from": sorted_dates[i - 1].isoformat(),
                        "to": sorted_dates[i].isoformat(),
                        "days": gap,
                    })

        results["work_pattern"] = {
            "commit_hours": hours,
            "peak_hour_utc": peak_hour,
            "inferred_utc_offset": inferred_utc_offset,
            "active_window": active_window,
            "active_days": list(days_active),
            "vacation_gaps": vacation_gaps,
            "cross_service_note": (
                "Cross-reference with Calendar events and email gaps "
                "to reconstruct full schedule"
            ),
        }
    except GithubException as e:
        results["work_pattern"] = {"error": str(e)}

    # --- SCOPE ANALYSIS (GitHub App fine-grained permissions) ---
    # Compute overprivilege from configured permissions vs what tools need
    granted_scopes = [
        {"scope": "contents:read", "permits": "Read all repository contents, code, files"},
        {"scope": "issues:write", "permits": "Create and edit issues in any accessible repo"},
        {"scope": "pull_requests:read", "permits": "Read pull requests and reviews"},
        {"scope": "secret_scanning:read", "permits": "Read secret scanning alerts"},
        {"scope": "email:read", "permits": "Read user email addresses"},
    ]
    # Scopes our scan tools actually NEED (not write tools)
    needed_for_scan = {"contents:read", "secret_scanning:read", "email:read"}
    # Scopes needed if write tools are used
    needed_for_remediation = {"issues:write"}
    # All needed = scan + remediation
    all_needed = needed_for_scan | needed_for_remediation
    granted_set = {s["scope"] for s in granted_scopes}
    unnecessary = granted_set - all_needed
    overprivilege_pct = round(len(unnecessary) / len(granted_set) * 100) if granted_set else 0

    results["scope_analysis"] = {
        "granted": granted_scopes,
        "needed_for_scan": list(needed_for_scan),
        "needed_for_remediation": list(needed_for_remediation),
        "unnecessary": list(unnecessary),
        "overprivilege_pct": overprivilege_pct,
        "recommended": [
            {"scope": s["scope"], "permits": s["permits"]}
            for s in granted_scopes if s["scope"] in all_needed
        ],
    }

    return results


@fga_tool_auth("scanGitHubExposure")
async def _scan_github_exposure() -> dict:
    """Async wrapper: FGA check (async) + sync scan in thread."""
    return await asyncio.to_thread(_scan_github_exposure_sync)


class ScanGitHubExposureSchema(BaseModel):
    pass

scan_github_exposure_tool = with_github(
    StructuredTool(
        name="scanGitHubExposure",
        description=(
            "Scan GitHub for exposure: read secret scanning alerts (200+ patterns), "
            "detect PII in commits, analyze work patterns, assess scope overprivilege"
        ),
        args_schema=ScanGitHubExposureSchema,
        coroutine=_scan_github_exposure,
    )
)
