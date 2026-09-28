"""
Assignment 11 — Audit Log starter (TODO).

Records every interaction for forensics. Never blocks by itself —
other layers catch attacks; this layer makes them reviewable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import time


def default_audit_log_path() -> str:
    """Always resolve to <repo>/outputs/… (safe when cwd is src/)."""
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / "outputs" / "audit_log.json")


class AuditLogPlugin:
    """Framework-agnostic audit logger (wire into ADK callbacks or your pipeline)."""

    def __init__(self):
        self.name = "audit_log"
        self.logs: list[dict] = []
        self._open: dict[str, dict] = {}

    def record_input(self, *, user_id: str, text: str, request_id: str | None = None):
        """Store input metadata and return the correlation/request ID."""
        correlation_id = request_id or user_id
        self._open[correlation_id] = {
            "request_id": correlation_id,
            "user_id": user_id,
            "input": text,
            "started_at": utc_now_iso(),
            "started_monotonic": time.perf_counter(),
        }
        return correlation_id

    def record_output(
        self,
        *,
        user_id: str,
        text: str,
        blocked: bool = False,
        layer: str | None = None,
        request_id: str | None = None,
    ):
        """Finish an interaction and append a JSON-serializable audit entry."""
        correlation_id = request_id or user_id
        started = self._open.pop(correlation_id, None)
        if started is None:
            started = {
                "request_id": correlation_id,
                "user_id": user_id,
                "input": "",
                "started_at": utc_now_iso(),
                "started_monotonic": time.perf_counter(),
            }
        latency_ms = max(
            0.0, (time.perf_counter() - started.pop("started_monotonic")) * 1000
        )
        self.logs.append({
            **started,
            "output": text,
            "blocked": blocked,
            "layer": layer,
            "completed_at": utc_now_iso(),
            "latency_ms": round(latency_ms, 3),
        })

    def export_json(self, filepath: str | None = None):
        """Write logs to disk (JSON array) under repo-root ``outputs/`` by default."""
        path = Path(filepath or default_audit_log_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.logs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
