# ◉ Sentinel QA — Desktop API Test Harness

A genuinely useful, zero-dependency GUI tool for QA engineers and developers to
**build, run and report on HTTP API test suites** — a lightweight, scriptable
cross between Postman and a CI smoke-test runner.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Dependencies](https://img.shields.io/badge/runtime%20deps-none-brightgreen)
![Tests](https://img.shields.io/badge/tests-pytest-informational)

## Why it exists

API regression checks are usually either (a) heavyweight hosted tools with
accounts and sync, or (b) throwaway curl scripts nobody maintains. Sentinel QA
sits in the sweet spot: suites are **plain JSON files** you can commit to the
repo next to the code they test, the engine is **stdlib-only** so it runs
anywhere, and results export to a self-contained HTML report you can attach to
a bug ticket or release note.

## Features

- **Visual test builder** — method, URL, headers, JSON body, per-request timeout
- **8 assertion kinds**: `status_equals`, `status_in`, `body_contains`,
  `body_not_contains`, `header_equals`, `json_path_equals` (dotted paths like
  `args.items[0].id`, with type-aware comparison), `json_path_exists`,
  `latency_under_ms`
- **Live results** — color-coded PASS / FAIL / ERROR with latency per test,
  streaming in as the suite runs (non-blocking worker thread)
- **Response inspector** — status line, headers and pretty-printed JSON body
- **Suite persistence** — save/load suites as JSON, duplicate cases, re-order
  by selection; 4xx/5xx responses are treated as *testable responses*, not crashes
- **Reports** — one-click export to a styled, self-contained **HTML report**
  (safe: all output HTML-escaped) or machine-readable **JSON**
- **Keyboard-first** — `F5` run all, `F6` run selected, `Ctrl+S/O/N`, `Esc` stop

## Run it

```bash
python -m sentinel_qa.app
```

No installation needed beyond Python 3.10+ — the GUI is tkinter (ships with
Python) and the HTTP engine is urllib.

## Test it

```bash
pip install -r requirements-dev.txt
pytest -q
```

The test suite spins up an in-process HTTP server, so it runs fully offline
and covers the assertion engine, JSON-path resolver, live HTTP round-trips,
suite round-tripping and report escaping.

## Architecture

```
sentinel_qa/
├── model.py    # dataclasses: TestCase, Assertion, TestResult — pure data
├── engine.py   # HTTP execution + assertion evaluation (stdlib only, testable)
├── report.py   # suite JSON persistence + HTML/JSON report generation
└── app.py      # tkinter GUI: dark theme, treeview suite list, editor tabs
tests/
└── test_engine.py   # offline pytest suite (local HTTP fixture)
examples/
└── httpbin_smoke_suite.json   # ready-to-run smoke suite against httpbin.org
```

The engine has **no GUI imports** — reuse it headless from scripts or CI:

```python
from sentinel_qa.report import load_suite, results_to_json
from sentinel_qa.engine import run_suite

_, cases = load_suite("examples/httpbin_smoke_suite.json")
results = run_suite(cases)
print(results_to_json(results, "ci smoke"))
raise SystemExit(0 if all(r.passed for r in results) else 1)
```

## License

MIT
