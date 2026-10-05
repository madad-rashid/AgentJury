"""Strict, versioned benchmark case loading."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .protocol import ReviewRequest


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    task: str
    output: str
    label: Literal["correct", "flawed", "injected"]
    context: str | None = None

    @field_validator("id", "task", "output")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be nonempty")
        return value


class _CasePack(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"]
    cases: list[BenchmarkCase]

    @model_validator(mode="after")
    def unique_and_nonempty(self) -> "_CasePack":
        ids = [case.id for case in self.cases]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique and pack nonempty")
        return self


PACKS = {"starter": "starter.json", "code": "code_cases.json"}


def load_cases(path: Path | None, pack: str = "starter") -> tuple[list[BenchmarkCase], str]:
    """Cases from ``path``, or from the packaged ``pack`` (``starter`` or ``code``) when ``path`` is None."""
    try:
        if path is not None:
            raw = path.read_bytes()
        else:
            raw = resources.files("agentjury").joinpath(f"data/{PACKS[pack]}").read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError("UTF-8 BOM is unsupported")
        pack = _CasePack.model_validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid case file ({type(exc).__name__}).") from None
    return pack.cases, hashlib.sha256(raw).hexdigest()


def case_hash(case: BenchmarkCase) -> str:
    content = {"task": case.task, "output": case.output, "context": case.context}
    raw = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def case_request(case: BenchmarkCase) -> ReviewRequest:
    return ReviewRequest(request_id=case_hash(case)[:12], task=case.task, output=case.output, context=case.context)
