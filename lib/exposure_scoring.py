"""Transparent, auditable exposure scoring engine.

Each component is independently meaningful. Weights are visible in the dashboard.
The user sees WHY the score is what it is.

Pure computation — no Auth0 dependencies, no async, no network calls.
"""


def compute_exposure_score(
    github_results: dict,
    google_results: dict,
    slack_results: dict | None = None,
    remediated_count: int = 0,
) -> dict:
    """Compute a transparent exposure score (0-100) from scan results.

    Returns:
        dict with score, components (breakdown), cross_service_findings,
        and remediation_actions (each mapping to a CIBA-gated tool call).
    """
    components = {}

    # --- Data surface: how much is accessible ---
    # Each sub-component normalized independently to avoid one dominating
    repo_count = github_results.get("repos", {}).get("total", 0)
    email_count = google_results.get("email", {}).get("totalThreads", 0)
    event_count = google_results.get("calendar", {}).get("upcomingEvents", 0)
    repo_score = min(33, repo_count * 2)
    email_score = min(33, min(email_count, 10000) / 300)
    event_score = min(34, event_count * 1.5)
    data_score = repo_score + email_score + event_score
    components["data_surface"] = {
        "score": round(data_score),
        "weight": 0.20,
        "explanation": f"{repo_count} repos + {email_count} emails + {event_count} calendar events accessible",
    }

    # --- Secrets exposed: alerts from GitHub's built-in secret scanning ---
    secrets_data = github_results.get("secrets", {})
    secrets = secrets_data.get("alerts", []) if isinstance(secrets_data, dict) else []
    secret_count = len(secrets)
    # Each secret is 25 points (CRITICAL severity), capped at 100
    components["secrets_exposed"] = {
        "score": min(100, secret_count * 25),
        "weight": 0.35,
        "explanation": (
            f"{secret_count} credential pattern(s) found via GitHub secret scanning"
            if secret_count
            else "No credential patterns detected"
        ),
    }

    # --- Overprivilege: granted vs needed scopes ---
    overprivilege = github_results.get("scope_analysis", {}).get("overprivilege_pct", 0)
    components["overprivilege"] = {
        "score": overprivilege,
        "weight": 0.25,
        "explanation": f"Granted scopes exceed needed by {overprivilege}%",
    }

    # --- PII exposure: personal identifiers in public data ---
    emails_exposed = github_results.get("email_exposure", {})
    email_list = emails_exposed.get("emails", []) if isinstance(emails_exposed, dict) else []
    pii_score = min(100, len(email_list) * 35)
    components["pii_exposure"] = {
        "score": pii_score,
        "weight": 0.20,
        "explanation": (
            f"{len(email_list)} email(s) found in public commit metadata"
            if email_list
            else "No PII detected in public commits"
        ),
    }

    # --- Remediation weight reduction ---
    # Findings with tracking issues get 50% weight reduction on secrets component
    if remediated_count > 0 and secret_count > 0:
        reduction = min(remediated_count / secret_count, 1.0) * 0.5
        components["secrets_exposed"]["score"] = round(
            components["secrets_exposed"]["score"] * (1 - reduction)
        )
        components["secrets_exposed"]["explanation"] += (
            f" ({remediated_count} remediated — {round(reduction * 100)}% weight reduction)"
        )

    # --- Weighted total ---
    total = sum(c["score"] * c["weight"] for c in components.values())

    # --- Cross-service correlation bonus ---
    cross_service_findings = []
    if email_list and google_results.get("email"):
        cross_service_findings.append(
            "Email in GitHub commits matches Google connection — identity bridge detected"
        )
    utc_offset = github_results.get("work_pattern", {}).get("inferred_utc_offset")
    if utc_offset is not None and google_results.get("calendar"):
        cross_service_findings.append(
            "Timezone from commits can be cross-referenced with Calendar event times"
        )
    if slack_results and slack_results.get("channels"):
        cross_service_findings.append(
            "Slack workspace membership adds another identity vector"
        )

    # --- Prioritized remediation actions ---
    remediation_actions = []
    if secret_count > 0:
        for s in secrets[:3]:
            remediation_actions.append({
                "action": "createIssue",
                "description": (
                    f"Create issue to rotate {s.get('secret_type', 'credential')} "
                    f"in {s.get('repo', 'repo')}"
                ),
                "severity": "CRITICAL",
                "ciba_required": True,
            })
    if email_list:
        remediation_actions.append({
            "action": "createIssue",
            "description": "Create issue to configure git noreply email for public commits",
            "severity": "MEDIUM",
            "ciba_required": True,
        })
    if overprivilege > 40:
        remediation_actions.append({
            "action": "createIssue",
            "description": f"Create issue to document scope downgrade (reduce by {overprivilege}%)",
            "severity": "MEDIUM",
            "ciba_required": True,
        })
    remediation_actions.append({
        "action": "disableMyTool",
        "description": "Agent self-restricts: disable unused write tools for this session",
        "severity": "INFO",
        "ciba_required": False,
    })

    return {
        "score": round(total),
        "components": components,
        "cross_service_findings": cross_service_findings,
        "remediation_actions": remediation_actions,
    }
