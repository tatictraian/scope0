"""Compute exposure score from scan results.

Used for post-remediation re-scoring. The initial score is computed
server-side deterministically (api_server.py auto-score).
The LLM calls this tool after creating remediation issues to show the score delta.
"""

import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lib.exposure_scoring import compute_exposure_score


class GenerateExposureScoreSchema(BaseModel):
    github_results: str = Field(default="{}", description="EXACT raw JSON string from scanGitHubExposure. Copy the entire output.")
    google_results: str = Field(default="{}", description="EXACT raw JSON string from scanGoogleExposure. Copy the entire output.")
    slack_results: str = Field(default="{}", description="Raw JSON from scanSlackExposure if available")
    remediated_count: int = Field(default=0, description="Number of findings with tracking issues created")


def _generate_exposure_score(
    github_results: str = "{}",
    google_results: str = "{}",
    slack_results: str = "{}",
    remediated_count: int = 0,
) -> dict:
    """Compute exposure score from scan results.

    Pass the EXACT raw JSON output from scanGitHubExposure and scanGoogleExposure.
    Do NOT summarize or modify the data.
    """
    try:
        gh = json.loads(github_results) if isinstance(github_results, str) else github_results
    except (json.JSONDecodeError, TypeError):
        gh = {}
    try:
        go = json.loads(google_results) if isinstance(google_results, str) else google_results
    except (json.JSONDecodeError, TypeError):
        go = {}
    try:
        sl = json.loads(slack_results) if isinstance(slack_results, str) else slack_results
    except (json.JSONDecodeError, TypeError):
        sl = {}

    return compute_exposure_score(gh, go, sl, remediated_count=int(remediated_count))


generate_exposure_score_tool = StructuredTool(
    name="generateExposureScore",
    description=(
        "Re-compute exposure score after remediation. "
        "Pass the raw JSON from scan results and set remediated_count to show score delta."
    ),
    args_schema=GenerateExposureScoreSchema,
    func=_generate_exposure_score,
)
