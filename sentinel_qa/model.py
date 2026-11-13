"""Domain model for Sentinel QA.

Pure data structures, no I/O. A *suite* is a list of :class:`TestCase`
objects; each case carries :class:`Assertion` objects and produces a
:class:`TestResult` when executed by the engine.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

ASSERTION_KINDS = (
    "status_equals",       # expected: "200"
    "status_in",           # expected: "200,201,204"
    "body_contains",       # expected: substring
    "body_not_contains",   # expected: substring
    "json_path_equals",    # target: dotted.path[0], expected: value (JSON-parsed if possible)
    "json_path_exists",    # target: dotted.path
    "header_equals",       # target: header name, expected: value
    "latency_under_ms",    # expected: milliseconds
)


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Assertion:
    kind: str = "status_equals"
    target: str = ""          # used by json_path_* and header_equals
    expected: str = "200"
    id: str = field(default_factory=_new_id)

    def describe(self) -> str:
        label = self.kind.replace("_", " ")
        if self.target:
            return f"{label}: {self.target} -> {self.expected}".rstrip(" ->")
        return f"{label}: {self.expected}"


@dataclass
class TestCase:
    name: str = "New test"
    method: str = "GET"
    url: str = "https://"
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    timeout_s: float = 10.0
    assertions: list[Assertion] = field(default_factory=list)
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestCase":
        data = dict(data)
        data["assertions"] = [Assertion(**a) for a in data.get("assertions", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    actual: str = ""
    detail: str = ""


@dataclass
class TestResult:
    case: TestCase
    status_code: Optional[int] = None
    latency_ms: float = 0.0
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str = ""
    error: str = ""
    assertion_results: list[AssertionResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def passed(self) -> bool:
        return not self.error and all(r.passed for r in self.assertion_results)

    @property
    def verdict(self) -> str:
        if self.error:
            return "ERROR"
        return "PASS" if self.passed else "FAIL"
