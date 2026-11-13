"""Suite persistence (JSON) and shareable HTML/JSON report generation."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Iterable

from .model import TestCase, TestResult
from . import __version__

SUITE_FORMAT = "sentinel-qa-suite"


def save_suite(cases: Iterable[TestCase], path: str | Path, name: str = "Untitled suite") -> None:
    payload = {
        "format": SUITE_FORMAT,
        "version": __version__,
        "name": name,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cases": [c.to_dict() for c in cases],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_suite(path: str | Path) -> tuple[str, list[TestCase]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("format") != SUITE_FORMAT:
        raise ValueError(f"{path} is not a Sentinel QA suite file")
    return payload.get("name", "Untitled suite"), [
        TestCase.from_dict(c) for c in payload.get("cases", [])
    ]


def results_to_json(results: Iterable[TestResult], suite_name: str) -> str:
    results = list(results)
    passed = sum(1 for r in results if r.verdict == "PASS")
    return json.dumps({
        "suite": suite_name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total": len(results), "passed": passed,
            "failed": sum(1 for r in results if r.verdict == "FAIL"),
            "errors": sum(1 for r in results if r.verdict == "ERROR"),
            "duration_ms": round(sum(r.latency_ms for r in results), 1),
        },
        "results": [{
            "name": r.case.name, "method": r.case.method, "url": r.case.url,
            "verdict": r.verdict, "status_code": r.status_code,
            "latency_ms": round(r.latency_ms, 1), "error": r.error,
            "assertions": [{
                "assertion": ar.assertion.describe(), "passed": ar.passed,
                "actual": ar.actual, "detail": ar.detail,
            } for ar in r.assertion_results],
        } for r in results],
    }, indent=2)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Sentinel QA report — {suite}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
      background:#0f1420;color:#e6e9f2;margin:0;padding:32px;}}
 h1{{font-size:22px;margin:0 0 4px}} .meta{{color:#8a93a8;font-size:13px;margin-bottom:24px}}
 .cards{{display:flex;gap:12px;margin-bottom:24px}}
 .card{{background:#1a2132;border:1px solid #2a3348;border-radius:10px;
       padding:14px 22px;min-width:110px}}
 .card b{{display:block;font-size:26px}} .pass{{color:#3fd68f}}
 .fail{{color:#ff6b6b}} .err{{color:#ffb454}} .muted{{color:#8a93a8}}
 table{{width:100%;border-collapse:collapse;background:#1a2132;
       border:1px solid #2a3348;border-radius:10px;overflow:hidden}}
 th,td{{padding:10px 14px;text-align:left;font-size:13.5px;
        border-bottom:1px solid #2a3348;vertical-align:top}}
 th{{background:#222a3d;color:#9fb0d0;text-transform:uppercase;
    font-size:11px;letter-spacing:.06em}}
 tr:last-child td{{border-bottom:none}}
 .badge{{padding:2px 10px;border-radius:20px;font-size:11.5px;font-weight:600}}
 .b-pass{{background:#123c2c;color:#3fd68f}} .b-fail{{background:#452022;color:#ff6b6b}}
 .b-err{{background:#453620;color:#ffb454}}
 code{{background:#0b0f18;padding:1px 6px;border-radius:5px;font-size:12.5px}}
 .sub{{color:#8a93a8;font-size:12px}}
</style></head><body>
<h1>Sentinel QA — Test Report</h1>
<div class="meta">Suite <b>{suite}</b> &middot; generated {when} &middot; sentinel-qa {version}</div>
<div class="cards">
 <div class="card"><b>{total}</b><span class="muted">total</span></div>
 <div class="card"><b class="pass">{passed}</b><span class="muted">passed</span></div>
 <div class="card"><b class="fail">{failed}</b><span class="muted">failed</span></div>
 <div class="card"><b class="err">{errors}</b><span class="muted">errors</span></div>
 <div class="card"><b>{duration} ms</b><span class="muted">total latency</span></div>
</div>
<table><thead><tr><th>Verdict</th><th>Test</th><th>Request</th>
<th>Status</th><th>Latency</th><th>Assertions</th></tr></thead><tbody>
{rows}
</tbody></table></body></html>"""


def results_to_html(results: Iterable[TestResult], suite_name: str) -> str:
    results = list(results)
    rows = []
    for r in results:
        badge = {"PASS": ("b-pass", "PASS"), "FAIL": ("b-fail", "FAIL"),
                 "ERROR": ("b-err", "ERROR")}[r.verdict]
        asserts = "<br>".join(
            f"{'&#10003;' if ar.passed else '&#10007;'} "
            f"<span class='sub'>{html.escape(ar.assertion.describe())}"
            f"{(' — got <code>' + html.escape(ar.actual[:80]) + '</code>') if not ar.passed else ''}</span>"
            for ar in r.assertion_results) or "<span class='sub'>—</span>"
        if r.error:
            asserts += f"<br><span class='fail'>{html.escape(r.error)}</span>"
        rows.append(
            f"<tr><td><span class='badge {badge[0]}'>{badge[1]}</span></td>"
            f"<td>{html.escape(r.case.name)}</td>"
            f"<td><code>{r.case.method}</code> <span class='sub'>{html.escape(r.case.url)}</span></td>"
            f"<td>{r.status_code if r.status_code is not None else '—'}</td>"
            f"<td>{r.latency_ms:.0f} ms</td><td>{asserts}</td></tr>")
    passed = sum(1 for r in results if r.verdict == "PASS")
    failed = sum(1 for r in results if r.verdict == "FAIL")
    errors = sum(1 for r in results if r.verdict == "ERROR")
    return _HTML_TEMPLATE.format(
        suite=html.escape(suite_name), when=time.strftime("%Y-%m-%d %H:%M:%S"),
        version=__version__, total=len(results), passed=passed, failed=failed,
        errors=errors, duration=f"{sum(r.latency_ms for r in results):.0f}",
        rows="\n".join(rows))
