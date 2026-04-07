from tools.scan_github import scan_github_exposure_tool
from tools.scan_google import scan_google_exposure_tool
from tools.list_prs import list_pull_requests_tool
from tools.search_emails import search_emails_tool
from tools.list_events import list_calendar_events_tool
from tools.create_issue import create_issue_tool
from tools.send_email import send_email_tool
from tools.generate_score import generate_exposure_score_tool
from tools.analyze_session import analyze_session_tool
from tools.self_restrict import disable_my_tool

# Slack tools exist (scan_slack.py, list_channels.py) but are not registered
# because no Slack connection is configured. UI shows "Coming Soon" badge.

ALL_TOOLS = [
    scan_github_exposure_tool,       # withGitHub + FGA
    scan_google_exposure_tool,       # withGoogle + FGA
    list_pull_requests_tool,         # withGitHub + FGA
    search_emails_tool,              # withGoogle + FGA
    list_calendar_events_tool,       # withGoogle + FGA
    create_issue_tool,               # withGitHub + CIBA + FGA
    send_email_tool,                 # withGoogle + CIBA + FGA
    generate_exposure_score_tool,    # No wrappers — for post-remediation re-scoring
    analyze_session_tool,            # No wrappers — session analysis
    disable_my_tool,                 # No wrappers — agent self-restriction via FGA
]
