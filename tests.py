#!/usr/bin/env python3
"""Scope0 smoke tests. Run: python tests.py"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


print("=== Scope0 Smoke Tests ===\n")

# --- Scoring Engine ---
print("Scoring Engine:")
from lib.exposure_scoring import compute_exposure_score

# Normal data
r = compute_exposure_score(
    {"repos": {"total": 10}, "secrets": {"alerts": [{"secret_type": "AWS", "repo": "x"}]},
     "email_exposure": {"emails": ["a@b.com"]}, "scope_analysis": {"overprivilege_pct": 40}},
    {"email": {"totalThreads": 500}, "calendar": {"upcomingEvents": 5}},
)
test("score is int", isinstance(r["score"], int))
test("score > 0 with findings", r["score"] > 0)
test("score <= 100", r["score"] <= 100)
test("has 4 components", len(r["components"]) == 4)
test("has cross_service_findings", isinstance(r["cross_service_findings"], list))
test("has remediation_actions", len(r["remediation_actions"]) > 0)

# Empty data
r0 = compute_exposure_score({}, {})
test("empty data score = 0", r0["score"] == 0)

# Remediation reduces score
r_rem = compute_exposure_score(
    {"repos": {"total": 5}, "secrets": {"alerts": [{"secret_type": "key", "repo": "r"}]},
     "email_exposure": {"emails": []}, "scope_analysis": {"overprivilege_pct": 30}},
    {"email": {"totalThreads": 100}, "calendar": {"upcomingEvents": 2}},
    remediated_count=1,
)
r_no_rem = compute_exposure_score(
    {"repos": {"total": 5}, "secrets": {"alerts": [{"secret_type": "key", "repo": "r"}]},
     "email_exposure": {"emails": []}, "scope_analysis": {"overprivilege_pct": 30}},
    {"email": {"totalThreads": 100}, "calendar": {"upcomingEvents": 2}},
    remediated_count=0,
)
test("remediation reduces score", r_rem["score"] < r_no_rem["score"])

# Data surface normalization — high email count shouldn't saturate to 100
r_high = compute_exposure_score(
    {"repos": {"total": 5}, "secrets": {"alerts": []},
     "email_exposure": {"emails": []}, "scope_analysis": {"overprivilege_pct": 0}},
    {"email": {"totalThreads": 50000}, "calendar": {"upcomingEvents": 0}},
)
test("data_surface < 100 with 50K emails", r_high["components"]["data_surface"]["score"] < 100)

# --- Timezone Inference ---
print("\nTimezone Inference:")


def simulate_tz_inference(hours_dict):
    """Replicate the gap-based algorithm from scan_github.py"""
    active_hours = sorted(hours_dict.keys())
    if len(active_hours) < 3:
        return None
    max_gap = 0
    gap_end = active_hours[0]
    for i in range(len(active_hours)):
        next_i = (i + 1) % len(active_hours)
        gap = (active_hours[next_i] - active_hours[i]) % 24
        if gap > max_gap:
            max_gap = gap
            gap_end = active_hours[next_i]
    gap_start_idx = (active_hours.index(gap_end) - 1) % len(active_hours)
    active_start = gap_end
    active_end = active_hours[gap_start_idx]
    if active_end >= active_start:
        center = (active_start + active_end) / 2
    else:
        center = ((active_start + active_end + 24) / 2) % 24
    offset = round(13 - center)
    if offset > 12:
        offset -= 24
    elif offset < -12:
        offset += 24
    return offset


test("UTC+2 worker", simulate_tz_inference({7: 2, 8: 5, 9: 8, 10: 10, 11: 8, 12: 6, 13: 5, 14: 3, 15: 1}) == 2)
test("UTC-5 worker", simulate_tz_inference({14: 2, 15: 5, 16: 8, 17: 10, 18: 8, 19: 6, 20: 5, 21: 3, 22: 1}) == -5)
test("UTC+0 worker", simulate_tz_inference({9: 2, 10: 5, 11: 8, 12: 10, 13: 8, 14: 6, 15: 5, 16: 3, 17: 1}) == 0)
test("UTC+9 worker", simulate_tz_inference({0: 2, 1: 5, 2: 8, 3: 10, 4: 8, 5: 6, 6: 5, 7: 3, 8: 1}) == 9)
test("too few hours returns None", simulate_tz_inference({10: 1, 11: 1}) is None)

# --- Tool Count ---
print("\nTool Registration:")
os.environ.setdefault("AUTH0_DOMAIN", "test")
os.environ.setdefault("AUTH0_CLIENT_ID", "test")
os.environ.setdefault("AUTH0_CLIENT_SECRET", "test")
os.environ.setdefault("GOOGLE_API_KEY", "test")
from tools import ALL_TOOLS

test("10 tools registered", len(ALL_TOOLS) == 10, f"got {len(ALL_TOOLS)}")
tool_names = [t.name for t in ALL_TOOLS]
test("scanGitHubExposure present", "scanGitHubExposure" in tool_names)
test("scanGoogleExposure present", "scanGoogleExposure" in tool_names)
test("createIssue present", "createIssue" in tool_names)
test("sendEmail present", "sendEmail" in tool_names)
test("generateExposureScore present", "generateExposureScore" in tool_names)
test("analyzeSession present", "analyzeSession" in tool_names)
test("disableMyTool present", "disableMyTool" in tool_names)
test("scanSlackExposure NOT in tools", "scanSlackExposure" not in tool_names)
test("listSlackChannels NOT in tools", "listSlackChannels" not in tool_names)

# --- Audit Store ---
print("\nAudit Store:")
from lib.audit_store import (
    store_scan_result, store_exposure_score, store_self_restriction,
    get_audit_timeline, save_last_session, get_last_session,
)

test_uid = "test|smoke"
store_scan_result(test_uid, "scanGitHubExposure", {"repos": {"total": 5}})
store_exposure_score(test_uid, {"score": 42, "components": {}, "cross_service_findings": [], "remediation_actions": []})
store_self_restriction(test_uid, "sendEmail", "test reason")
save_last_session(test_uid, {"scanGitHubExposure": {}}, {"score": 42})

timeline = get_audit_timeline(test_uid)
test("timeline has entries", len(timeline) >= 3)

session = get_last_session(test_uid)
test("session restore works", session is not None and "scans" in session and "score" in session)

# --- Generate Score Tool ---
print("\nGenerate Score Tool:")
from tools.generate_score import _generate_exposure_score

result = _generate_exposure_score(
    '{"repos":{"total":5},"secrets":{"alerts":[]},"email_exposure":{"emails":[]},"scope_analysis":{"overprivilege_pct":20}}',
    '{"email":{"totalThreads":100},"calendar":{"upcomingEvents":5}}',
)
test("generates score from JSON strings", isinstance(result["score"], int))

bad_result = _generate_exposure_score("invalid", "also bad")
test("handles bad JSON gracefully", bad_result["score"] == 0)

# --- Summary ---
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed == 0:
    print("ALL TESTS PASS")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
