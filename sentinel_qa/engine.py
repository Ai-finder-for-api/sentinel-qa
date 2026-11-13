"""Execution engine: performs HTTP requests and evaluates assertions.

Stdlib-only (urllib) so the tool runs anywhere Python does. The engine is
deliberately separated from the GUI so it can be unit-tested and reused
from scripts or CI.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterable, Optional

from .model import Assertion, AssertionResult, TestCase, TestResult

MAX_BODY_CHARS = 200_000  # keep results memory-safe


class EngineError(Exception):
    """Raised for malformed test definitions."""


# --------------------------------------------------------------------------
# JSON path helpers (dotted paths with optional [index] segments)
# --------------------------------------------------------------------------

def resolve_json_path(document: Any, path: str) -> Any:
    """Resolve ``a.b[0].c`` against parsed JSON. Raises KeyError/IndexError."""
    if not path:
        return document
    current = document
    for segment in path.split("."):
        name, _, rest = segment.partition("[")
        if name:
            if not isinstance(current, dict) or name not in current:
                raise KeyError(f"missing key '{name}'")
            current = current[name]
        while rest:
            idx_str, _, rest = rest.partition("]")
            current = current[int(idx_str)]
            rest = rest.lstrip("[")
    return current


def _coerce_like(value: str, sample: Any) -> Any:
    """Parse ``value`` as JSON if possible so '200' can equal int 200."""
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def execute_request(case: TestCase) -> TestResult:
    """Fire the HTTP request described by *case* and capture the response."""
    result = TestResult(case=case)
    if not case.url.lower().startswith(("http://", "https://")):
        result.error = f"URL must start with http:// or https:// (got {case.url!r})"
        return result

    body_bytes: Optional[bytes] = None
    headers = dict(case.headers)
    if case.body and case.method in ("POST", "PUT", "PATCH", "DELETE"):
        body_bytes = case.body.encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        case.url, data=body_bytes, headers=headers, method=case.method
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=case.timeout_s) as resp:
            raw = resp.read(MAX_BODY_CHARS + 1)
            result.status_code = resp.status
            result.response_headers = {k: v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:  # 4xx/5xx are valid responses for QA
        raw = exc.read(MAX_BODY_CHARS + 1)
        result.status_code = exc.code
        result.response_headers = {k: v for k, v in (exc.headers or {}).items()}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result.latency_ms = (time.perf_counter() - started) * 1000
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    result.latency_ms = (time.perf_counter() - started) * 1000
    result.response_body = raw[:MAX_BODY_CHARS].decode("utf-8", errors="replace")
    return result


# --------------------------------------------------------------------------
# Assertions
# --------------------------------------------------------------------------

def evaluate_assertion(assertion: Assertion, result: TestResult) -> AssertionResult:
    kind, target, expected = assertion.kind, assertion.target, assertion.expected
    body = result.response_body
    out = AssertionResult(assertion=assertion, passed=False)

    if kind == "status_equals":
        out.actual = str(result.status_code)
        out.passed = result.status_code == int(expected)
    elif kind == "status_in":
        allowed = {int(x.strip()) for x in expected.split(",") if x.strip()}
        out.actual = str(result.status_code)
        out.passed = result.status_code in allowed
    elif kind == "body_contains":
        out.actual = body[:200]
        out.passed = expected in body
    elif kind == "body_not_contains":
        out.actual = body[:200]
        out.passed = expected not in body
    elif kind == "header_equals":
        headers = {k.lower(): v for k, v in result.response_headers.items()}
        out.actual = headers.get(target.lower(), "<missing>")
        out.passed = out.actual == expected
    elif kind in ("json_path_equals", "json_path_exists"):
        try:
            document = json.loads(body) if body else None
        except ValueError:
            out.actual = "<unparseable JSON>"
            out.detail = "response body is not valid JSON"
            return out
        try:
            value = resolve_json_path(document, target)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            out.actual = f"<path error: {exc}>"
            return out
        out.actual = json.dumps(value) if not isinstance(value, str) else value
        if kind == "json_path_exists":
            out.passed = True
        else:
            out.passed = value == _coerce_like(expected, value)
    elif kind == "latency_under_ms":
        out.actual = f"{result.latency_ms:.1f} ms"
        out.passed = result.latency_ms < float(expected)
    else:
        out.detail = f"unknown assertion kind {kind!r}"
    return out


def run_case(case: TestCase) -> TestResult:
    """Execute one case end-to-end: request + all assertions."""
    result = execute_request(case)
    if result.error:
        return result
    if not case.assertions:
        case.assertions.append(Assertion())  # sensible default: HTTP 200
    result.assertion_results = [evaluate_assertion(a, result) for a in case.assertions]
    return result


def run_suite(
    cases: Iterable[TestCase],
    on_result=None,
    should_stop=None,
) -> list[TestResult]:
    """Run *cases* sequentially. ``on_result(result, index, total)`` is invoked
    after each case (thread-safe for callers to marshal onto a UI thread)."""
    cases = list(cases)
    results: list[TestResult] = []
    for index, case in enumerate(cases):
        if should_stop and should_stop():
            break
        result = run_case(case)
        results.append(result)
        if on_result:
            on_result(result, index, len(cases))
    return results
