"""Unit tests for the Sentinel QA engine, model and report layers.

Runs fully offline: HTTP is exercised against a local in-process server.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sentinel_qa.model import Assertion, TestCase
from sentinel_qa.engine import (
    evaluate_assertion, execute_request, resolve_json_path, run_case, run_suite,
)
from sentinel_qa.model import TestResult
from sentinel_qa.report import (
    load_suite, results_to_html, results_to_json, save_suite,
)


# ---------------------------------------------------------------- json path
class TestResolveJsonPath:
    doc = {"a": {"b": [{"c": 1}, {"c": 2}]}, "name": "sentinel", "n": 42}

    def test_simple_key(self):
        assert resolve_json_path(self.doc, "name") == "sentinel"

    def test_nested(self):
        assert resolve_json_path(self.doc, "a.b[1].c") == 2

    def test_numeric_leaf(self):
        assert resolve_json_path(self.doc, "n") == 42

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            resolve_json_path(self.doc, "nope")

    def test_bad_index_raises(self):
        with pytest.raises(IndexError):
            resolve_json_path(self.doc, "a.b[9].c")


# ---------------------------------------------------------------- assertions
def make_result(status=200, body="{}", headers=None, latency=5.0):
    return TestResult(case=TestCase(), status_code=status, latency_ms=latency,
                      response_headers=headers or {}, response_body=body)


class TestAssertions:
    def test_status_equals(self):
        assert evaluate_assertion(Assertion("status_equals", "", "200"),
                                  make_result(200)).passed
        assert not evaluate_assertion(Assertion("status_equals", "", "201"),
                                      make_result(200)).passed

    def test_status_in(self):
        assert evaluate_assertion(Assertion("status_in", "", "200, 204"),
                                  make_result(204)).passed

    def test_body_contains(self):
        assert evaluate_assertion(Assertion("body_contains", "", "hello"),
                                  make_result(body="say hello world")).passed
        assert not evaluate_assertion(Assertion("body_not_contains", "", "hello"),
                                      make_result(body="say hello world")).passed

    def test_header_equals_case_insensitive(self):
        a = Assertion("header_equals", "Content-Type", "application/json")
        assert evaluate_assertion(a, make_result(headers={"content-type": "application/json"})).passed

    def test_json_path_equals_type_coercion(self):
        body = json.dumps({"args": {"page": 2}, "ok": True})
        assert evaluate_assertion(Assertion("json_path_equals", "args.page", "2"),
                                  make_result(body=body)).passed
        assert evaluate_assertion(Assertion("json_path_equals", "ok", "true"),
                                  make_result(body=body)).passed

    def test_json_path_exists_and_missing(self):
        body = json.dumps({"a": {"b": 1}})
        assert evaluate_assertion(Assertion("json_path_exists", "a.b", ""),
                                  make_result(body=body)).passed
        r = evaluate_assertion(Assertion("json_path_exists", "a.zzz", ""),
                               make_result(body=body))
        assert not r.passed and "path error" in r.actual

    def test_json_path_unparseable_body(self):
        r = evaluate_assertion(Assertion("json_path_exists", "a", ""),
                               make_result(body="not json"))
        assert not r.passed and r.detail

    def test_latency_under_ms(self):
        assert evaluate_assertion(Assertion("latency_under_ms", "", "10"),
                                  make_result(latency=5)).passed
        assert not evaluate_assertion(Assertion("latency_under_ms", "", "10"),
                                      make_result(latency=50)).passed


# ---------------------------------------------------------------- live HTTP
@pytest.fixture(scope="module")
def server():
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, payload, ctype="application/json"):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            if self.path == "/ok":
                self._reply(200, {"ok": True, "items": [1, 2, 3]})
            elif self.path == "/slow":
                time.sleep(0.15)
                self._reply(200, {"slow": True})
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            self._reply(201, {"echo": json.loads(body)})

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


class TestLiveHttp:
    def test_get_pass(self, server):
        case = TestCase(name="get ok", url=f"{server}/ok", assertions=[
            Assertion("status_equals", "", "200"),
            Assertion("json_path_equals", "items[2]", "3"),
            Assertion("latency_under_ms", "", "5000"),
        ])
        result = run_case(case)
        assert result.verdict == "PASS" and result.status_code == 200

    def test_post_echo(self, server):
        case = TestCase(name="post", method="POST", url=f"{server}/ok",
                        body=json.dumps({"x": 1}), assertions=[
                            Assertion("status_equals", "", "201"),
                            Assertion("json_path_equals", "echo.x", "1"),
                        ])
        assert run_case(case).verdict == "PASS"

    def test_404_is_valid_response(self, server):
        case = TestCase(name="missing", url=f"{server}/nope", assertions=[
            Assertion("status_equals", "", "404")])
        assert run_case(case).verdict == "PASS"

    def test_failing_assertion(self, server):
        case = TestCase(name="bad", url=f"{server}/ok", assertions=[
            Assertion("status_equals", "", "500")])
        assert run_case(case).verdict == "FAIL"

    def test_connection_refused_is_error(self):
        case = TestCase(name="down", url="http://127.0.0.1:1/", timeout_s=2)
        result = run_case(case)
        assert result.verdict == "ERROR" and result.error

    def test_bad_url_rejected(self):
        assert "http" in execute_request(TestCase(url="ftp://x")).error

    def test_run_suite_callback_order(self, server):
        cases = [TestCase(name=f"c{i}", url=f"{server}/ok") for i in range(3)]
        seen = []
        results = run_suite(cases, on_result=lambda r, i, n: seen.append((i, n)))
        assert seen == [(0, 3), (1, 3), (2, 3)]
        assert all(r.passed for r in results)


# ---------------------------------------------------------------- reports
class TestReports:
    def test_suite_roundtrip(self, tmp_path):
        cases = [TestCase(name="a", url="https://x.test",
                          headers={"X-T": "1"},
                          assertions=[Assertion("body_contains", "", "hi")])]
        path = tmp_path / "suite.json"
        save_suite(cases, path, "roundtrip")
        name, loaded = load_suite(path)
        assert name == "roundtrip"
        assert loaded[0].name == "a"
        assert loaded[0].headers == {"X-T": "1"}
        assert loaded[0].assertions[0].kind == "body_contains"

    def test_load_rejects_foreign_file(self, tmp_path):
        path = tmp_path / "junk.json"
        path.write_text("{}")
        with pytest.raises(ValueError):
            load_suite(path)

    def test_json_report_summary(self):
        results = [run_case(TestCase(url="http://127.0.0.1:1/", timeout_s=1))]
        data = json.loads(results_to_json(results, "s"))
        assert data["summary"]["errors"] == 1

    def test_html_report_escapes(self):
        r = make_result(200, "<script>alert(1)</script>")
        r.assertion_results = []
        html = results_to_html([r], "<b>suite</b>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;b&gt;suite&lt;/b&gt;" in html
