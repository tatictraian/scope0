"""Audit store — persists scan results and scores for timeline display.

Separate from LangGraph checkpoints. Stores:
- Scan results (per service, per user)
- Exposure scores with component breakdown
- Self-restriction events
- Timestamps for timeline ordering
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

_db_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scope0_audit.db",
)
_conn = sqlite3.connect(_db_path, check_same_thread=False)
_conn.row_factory = sqlite3.Row

# Create tables on import
_conn.executescript("""
    CREATE TABLE IF NOT EXISTS scan_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        scan_type TEXT NOT NULL,
        results_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS exposure_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        score INTEGER NOT NULL,
        components_json TEXT NOT NULL,
        cross_service_json TEXT NOT NULL,
        remediation_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS self_restrictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS last_session (
        user_id TEXT PRIMARY KEY,
        scan_data_json TEXT NOT NULL,
        score_data_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_scan_user ON scan_results(user_id);
    CREATE INDEX IF NOT EXISTS idx_score_user ON exposure_scores(user_id);
""")
_conn.commit()


def store_scan_result(user_id: str, scan_type: str, results: dict) -> None:
    """Store a scan result for the audit timeline."""
    _conn.execute(
        "INSERT INTO scan_results (user_id, scan_type, results_json, created_at) VALUES (?, ?, ?, ?)",
        (user_id, scan_type, json.dumps(results), datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def store_exposure_score(user_id: str, score_data: dict) -> None:
    """Store an exposure score computation for the timeline."""
    _conn.execute(
        "INSERT INTO exposure_scores (user_id, score, components_json, cross_service_json, remediation_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            user_id,
            score_data.get("score", 0),
            json.dumps(score_data.get("components", {})),
            json.dumps(score_data.get("cross_service_findings", [])),
            json.dumps(score_data.get("remediation_actions", [])),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    _conn.commit()


def store_self_restriction(user_id: str, tool_name: str, reason: str) -> None:
    """Store a self-restriction event."""
    _conn.execute(
        "INSERT INTO self_restrictions (user_id, tool_name, reason, created_at) VALUES (?, ?, ?, ?)",
        (user_id, tool_name, reason, datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def save_last_session(user_id: str, scan_data: dict, score_data: dict) -> None:
    """Save/update the last session's scan + score data for quick reload."""
    _conn.execute(
        "INSERT OR REPLACE INTO last_session (user_id, scan_data_json, score_data_json, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, json.dumps(scan_data), json.dumps(score_data), datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def get_last_session(user_id: str) -> dict | None:
    """Get the last session's scan + score data for replay on page refresh."""
    row = _conn.execute(
        "SELECT scan_data_json, score_data_json, updated_at FROM last_session WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "scans": json.loads(row["scan_data_json"]),
        "score": json.loads(row["score_data_json"]),
        "updated_at": row["updated_at"],
    }


def get_audit_timeline(user_id: str, limit: int = 20) -> list:
    """Get the audit timeline for a user — combined, chronologically ordered."""
    events = []

    # Scan results
    for row in _conn.execute(
        "SELECT scan_type, results_json, created_at FROM scan_results WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ):
        events.append({
            "type": "scan",
            "scan_type": row["scan_type"],
            "created_at": row["created_at"],
        })

    # Scores
    for row in _conn.execute(
        "SELECT score, components_json, cross_service_json, created_at FROM exposure_scores WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ):
        events.append({
            "type": "score",
            "score": row["score"],
            "components": json.loads(row["components_json"]),
            "cross_service": json.loads(row["cross_service_json"]),
            "created_at": row["created_at"],
        })

    # Self-restrictions
    for row in _conn.execute(
        "SELECT tool_name, reason, created_at FROM self_restrictions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ):
        events.append({
            "type": "self_restrict",
            "tool_name": row["tool_name"],
            "reason": row["reason"],
            "created_at": row["created_at"],
        })

    # Sort by time descending
    events.sort(key=lambda e: e["created_at"], reverse=True)
    return events[:limit]
