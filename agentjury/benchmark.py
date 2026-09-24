"""Sequential, resumable judge jobs for labeled benchmark cases."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .benchmark_cases import BenchmarkCase, case_hash, case_request
from .judges.base import CompletionBudgetExhausted, Judge
from .judges.compatible import OLLAMA_URL, OPENROUTER_URL
from .panel import Panel
from .panel_config import build_panel
from .protocol import Review


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Candidate:
    spec: str
    panel: Panel

    @property
    def is_free(self) -> bool:
        return all(
            judge.params.get("route") == "ollama"
            or (judge.params.get("route") == "openrouter" and judge.model.endswith(":free"))
            for judge in self.panel.judges
        )


def prepare(cases: list[BenchmarkCase], specs: list[str]) -> list[Candidate]:
    if not cases or not specs:
        raise ValueError("Benchmark needs cases and at least one panel.")
    if len(specs) != len(set(specs)):
        raise ValueError("Benchmark contains a duplicate panel spec.")
    candidates = [Candidate(spec, build_panel(spec)) for spec in specs]
    for candidate in candidates:
        _check_candidate(candidate)
    return candidates


def _check_candidate(candidate: Candidate) -> None:
    ids = [judge.config_id for judge in candidate.panel.judges]
    if len(ids) != len(set(ids)):
        raise ValueError("Panel contains a duplicate judge configuration.")


def job_key(case: BenchmarkCase, judge: Judge) -> str:
    return hashlib.sha256(f"{case_hash(case)}:{judge.config_id}".encode("ascii")).hexdigest()


def _metadata(cases: list[BenchmarkCase], candidates: list[Candidate]) -> tuple[list[dict], list[dict]]:
    case_rows = [{"id": case.id, "label": case.label, "hash": case_hash(case)} for case in cases]
    panel_rows = [
        {"spec": candidate.spec, "panel_id": candidate.panel.panel_id,
         "config_ids": [judge.config_id for judge in candidate.panel.judges],
         "providers": [judge.provider for judge in candidate.panel.judges],
         "free": candidate.is_free}
        for candidate in candidates
    ]
    return case_rows, panel_rows


def _jobs(cases: list[BenchmarkCase], candidates: list[Candidate]):
    seen = set()
    for case in cases:
        for candidate in candidates:
            for judge in candidate.panel.judges:
                key = job_key(case, judge)
                if key not in seen:
                    seen.add(key)
                    yield key, case, judge


def distinct_jobs(cases: list[BenchmarkCase], candidates: list[Candidate]) -> int:
    return sum(1 for _ in _jobs(cases, candidates))


def maximum_attempts(cases: list[BenchmarkCase], candidates: list[Candidate]) -> int:
    return sum(2 * (judge.retries + 1) for _, _, judge in _jobs(cases, candidates))


def _safe_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        match = re.search(r"\bHTTP ([1-5][0-9]{2})\b", str(exc))
        status = int(match.group(1)) if match else None
    suffix = f" HTTP {status}" if isinstance(status, int) else ""
    return f"{type(exc).__name__}{suffix}"


def _redact_review(review: Review, case: BenchmarkCase) -> dict:
    needles = [case.task, case.output, case.context or "", OPENROUTER_URL, OLLAMA_URL]
    needles += [os.environ.get(name, "") for name in (
        "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "AGENTJURY_COMPATIBLE_API_KEY", "AGENTJURY_COMPATIBLE_BASE_URL",
        "AGENTJURY_OLLAMA_BASE_URL",
    )]
    needles = sorted((needle for needle in needles if len(needle) >= 6), key=len, reverse=True)

    def clean(value):
        if isinstance(value, str):
            for needle in needles:
                value = value.replace(needle, "[redacted]")
            return value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    return clean(review.model_dump(mode="json"))


def _save(path: Path, report: dict, on_snapshot: Callable[[dict], dict] | None) -> dict:
    report["updated_at"] = _now()
    if on_snapshot:
        report = on_snapshot(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def run(
    cases: list[BenchmarkCase], pack_hash: str, candidates: list[Candidate], *,
    report_path: Path, max_calls: int = 20, resume: bool = False,
    retry_errors: bool = False, progress: Callable[[str], None] | None = None,
    on_snapshot: Callable[[dict], dict] | None = None,
) -> dict:
    if max_calls <= 0:
        raise ValueError("--max-calls must be positive.")
    if not cases or not candidates:
        raise ValueError("Benchmark needs cases and at least one panel.")
    for candidate in candidates:
        _check_candidate(candidate)
    case_rows, panel_rows = _metadata(cases, candidates)
    jobs = list(_jobs(cases, candidates))
    if resume:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Invalid resume report.") from None
        if (not isinstance(report, dict) or report.get("schema_version") != "1"
                or report.get("pack_hash") != pack_hash
                or report.get("cases") != case_rows or report.get("panels") != panel_rows
                or not isinstance(report.get("jobs"), dict)
                or not isinstance(report.get("calls_total"), int)
                or report["calls_total"] < 0):
            raise ValueError("Invalid resume report or inputs changed.")
        valid_keys = {key for key, _, _ in jobs}
        for key, item in report["jobs"].items():
            if key not in valid_keys or not isinstance(item, dict) or ("review" in item) == ("error" in item):
                raise ValueError("Invalid resume report jobs.")
            if "review" in item:
                try:
                    Review.model_validate(item["review"])
                except Exception:
                    raise ValueError("Invalid resume report review.") from None
            elif not isinstance(item["error"], str):
                raise ValueError("Invalid resume report error.")
    else:
        report = {
            "schema_version": "1", "created_at": _now(), "updated_at": _now(),
            "state": "partial", "pack_hash": pack_hash, "cases": case_rows,
            "panels": panel_rows, "jobs": {}, "calls_total": 0,
        }
    calls_this_run = 0
    for key, case, judge in jobs:
        old = report["jobs"].get(key)
        if old and ("review" in old or not retry_errors):
            continue
        if old:
            del report["jobs"][key]
            report["state"] = "partial"
        if calls_this_run >= max_calls:
            break
        original = judge.complete

        def budgeted(system: str, user: str):
            nonlocal calls_this_run, report
            if calls_this_run >= max_calls:
                raise CompletionBudgetExhausted()
            calls_this_run += 1
            report["calls_total"] += 1
            report = _save(report_path, report, on_snapshot)
            return original(system, user)

        judge.complete = budgeted
        try:
            review = judge.review(case_request(case))
            report["jobs"][key] = {"review": _redact_review(review, case), "completed_at": _now()}
            if progress:
                progress(f"{len(report['jobs'])}/{len(jobs)} {judge.name}: review saved")
        except CompletionBudgetExhausted:
            break
        except Exception as exc:
            error = _safe_error(exc)
            report["jobs"][key] = {"error": error, "completed_at": _now()}
            if progress:
                progress(f"{len(report['jobs'])}/{len(jobs)} {judge.name}: {error}")
        finally:
            judge.complete = original
        report["state"] = "complete" if len(report["jobs"]) == len(jobs) else "partial"
        report = _save(report_path, report, on_snapshot)
    report["state"] = "complete" if len(report["jobs"]) == len(jobs) else "partial"
    return _save(report_path, report, on_snapshot)
