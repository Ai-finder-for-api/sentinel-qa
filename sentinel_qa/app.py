"""Sentinel QA — desktop API test harness (tkinter GUI).

Run:  python -m sentinel_qa.app
"""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from .model import Assertion, TestCase, TestResult, HTTP_METHODS, ASSERTION_KINDS
from .engine import run_suite
from .report import save_suite, load_suite, results_to_html, results_to_json

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
BG        = "#0f1420"
PANEL     = "#171d2d"
PANEL_2   = "#1f2740"
BORDER    = "#2a3348"
FG        = "#e6e9f2"
MUTED     = "#8a93a8"
ACCENT    = "#4f8cff"
PASS      = "#3fd68f"
FAIL      = "#ff6b6b"
ERROR     = "#ffb454"
FONT      = ("Segoe UI", 10)
MONO      = ("JetBrains Mono", 10)  # falls back gracefully


def _apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=BG)
    style.configure(".", background=BG, foreground=FG, font=FONT,
                    fieldbackground=PANEL, bordercolor=BORDER, troughcolor=BG)
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Panel.TLabel", background=PANEL, foreground=FG)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Title.TLabel", background=BG, foreground=FG,
                    font=(FONT[0], 15, "bold"))
    style.configure("TButton", background=PANEL_2, foreground=FG,
                    bordercolor=BORDER, padding=(12, 6), focuscolor=ACCENT)
    style.map("TButton", background=[("active", "#2b3556")],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", "#3a74e0"),
                                            ("disabled", "#33415f")])
    style.configure("Danger.TButton", background="#5a2b33", foreground=FG)
    style.map("Danger.TButton", background=[("active", "#723844")])
    style.configure("TEntry", fieldbackground=PANEL, foreground=FG,
                    insertcolor=FG, bordercolor=BORDER)
    style.configure("TCombobox", fieldbackground=PANEL, foreground=FG,
                    arrowcolor=MUTED, bordercolor=BORDER)
    style.configure("TNotebook", background=BG, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                    padding=(16, 8))
    style.map("TNotebook.Tab", background=[("selected", PANEL_2)],
              foreground=[("selected", FG)])
    style.configure("Treeview", background=PANEL, foreground=FG,
                    fieldbackground=PANEL, bordercolor=BORDER, rowheight=28)
    style.configure("Treeview.Heading", background=PANEL_2, foreground=MUTED,
                    font=(FONT[0], 9, "bold"), padding=(8, 6))
    style.map("Treeview", background=[("selected", "#2b3a63")],
              foreground=[("selected", "#ffffff")])
    style.configure("TSpinbox", fieldbackground=PANEL, foreground=FG)
    style.configure("TSeparator", background=BORDER)
    return style


def _dark_text(parent, **kw) -> tk.Text:
    return tk.Text(parent, bg=PANEL, fg=FG, insertbackground=FG,
                   selectbackground="#2b3a63", relief="flat", bd=8,
                   font=MONO, wrap="none", undo=True, **kw)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
class SentinelApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Sentinel QA — API Test Harness")
        self.geometry("1240x780")
        self.minsize(980, 600)
        _apply_theme(self)

        self.cases: list[TestCase] = []
        self.results: dict[str, TestResult] = {}
        self.suite_name = tk.StringVar(value="Untitled suite")
        self.suite_path: Path | None = None
        self._queue: queue.Queue = queue.Queue()
        self._stop_flag = threading.Event()
        self._runner: threading.Thread | None = None
        self._loading_editor = False

        self._build_menu()
        self._build_toolbar()
        self._build_main()
        self._build_statusbar()
        self._bind_shortcuts()
        self.after(80, self._poll_queue)

        self._new_case()  # start with one example case

    # ---------------- UI construction ----------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self, bg=PANEL, fg=FG, activebackground=ACCENT,
                          activeforeground="#fff", bd=0)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="New suite", accelerator="Ctrl+N", command=self.new_suite)
        filem.add_command(label="Open suite…", accelerator="Ctrl+O", command=self.open_suite)
        filem.add_command(label="Save suite", accelerator="Ctrl+S", command=self.save_suite)
        filem.add_command(label="Save suite as…", command=lambda: self.save_suite(ask=True))
        filem.add_separator()
        filem.add_command(label="Export HTML report…", command=lambda: self.export_report("html"))
        filem.add_command(label="Export JSON report…", command=lambda: self.export_report("json"))
        filem.add_separator()
        filem.add_command(label="Quit", accelerator="Ctrl+Q", command=self.destroy)
        runm = tk.Menu(menubar, tearoff=0)
        runm.add_command(label="Run all tests", accelerator="F5", command=self.run_all)
        runm.add_command(label="Run selected", accelerator="F6", command=self.run_selected)
        runm.add_command(label="Stop", accelerator="Esc", command=self.stop_run)
        menubar.add_cascade(label="File", menu=filem)
        menubar.add_cascade(label="Run", menu=runm)
        self.config(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="TFrame", padding=(12, 10, 12, 4))
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text="◉ Sentinel QA", style="Title.TLabel").pack(side="left")
        ttk.Label(bar, text="  Suite:").pack(side="left", padx=(18, 4))
        name_entry = ttk.Entry(bar, textvariable=self.suite_name, width=28)
        name_entry.pack(side="left")
        ttk.Button(bar, text="Open", command=self.open_suite).pack(side="left", padx=(10, 0))
        ttk.Button(bar, text="Save", command=self.save_suite).pack(side="left", padx=4)
        ttk.Button(bar, text="▶ Run all", style="Accent.TButton",
                   command=self.run_all).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="Run selected", command=self.run_selected).pack(side="right", padx=4)
        self.stop_btn = ttk.Button(bar, text="■ Stop", style="Danger.TButton",
                                   command=self.stop_run, state="disabled")
        self.stop_btn.pack(side="right", padx=4)
        ttk.Button(bar, text="Export report", command=lambda: self.export_report("html")
                   ).pack(side="right", padx=4)

    def _build_main(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=8)

        # --- Left: test list ------------------------------------------------
        left = ttk.Frame(paned, style="Panel.TFrame", padding=8)
        paned.add(left, weight=1)
        ttk.Label(left, text="TEST CASES", style="Muted.TLabel",
                  font=(FONT[0], 9, "bold")).pack(anchor="w", pady=(0, 6))
        cols = ("method", "verdict", "latency")
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="Name")
        self.tree.heading("method", text="Method")
        self.tree.heading("verdict", text="Verdict")
        self.tree.heading("latency", text="Latency")
        self.tree.column("#0", width=210, stretch=True)
        self.tree.column("method", width=62, anchor="center", stretch=False)
        self.tree.column("verdict", width=66, anchor="center", stretch=False)
        self.tree.column("latency", width=72, anchor="e", stretch=False)
        self.tree.tag_configure("PASS", foreground=PASS)
        self.tree.tag_configure("FAIL", foreground=FAIL)
        self.tree.tag_configure("ERROR", foreground=ERROR)
        self.tree.tag_configure("PENDING", foreground=MUTED)
        self.tree.tag_configure("RUNNING", foreground=ACCENT)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = ttk.Frame(left, style="Panel.TFrame")
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="＋ Add", command=self._new_case).pack(side="left")
        ttk.Button(btns, text="Duplicate", command=self._duplicate_case).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete", style="Danger.TButton",
                   command=self._delete_cases).pack(side="left")

        # --- Right: editor notebook -----------------------------------------
        right = ttk.Frame(paned, style="Panel.TFrame", padding=10)
        paned.add(right, weight=3)
        self.editor = ttk.Notebook(right)
        self.editor.pack(fill="both", expand=True)
        self._build_request_tab()
        self._build_assertions_tab()
        self._build_response_tab()

    def _build_request_tab(self) -> None:
        tab = ttk.Frame(self.editor, style="Panel.TFrame", padding=10)
        self.editor.add(tab, text="  Request  ")

        row = ttk.Frame(tab, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Name", style="Panel.TLabel").pack(side="left")
        self.name_var = tk.StringVar()
        name = ttk.Entry(row, textvariable=self.name_var)
        name.pack(side="left", fill="x", expand=True, padx=(8, 0))
        name.bind("<KeyRelease>", lambda _e: self._editor_dirty(rename=True))

        row2 = ttk.Frame(tab, style="Panel.TFrame")
        row2.pack(fill="x", pady=(10, 0))
        self.method_var = tk.StringVar(value="GET")
        method = ttk.Combobox(row2, textvariable=self.method_var, values=HTTP_METHODS,
                              width=8, state="readonly")
        method.pack(side="left")
        method.bind("<<ComboboxSelected>>", lambda _e: self._editor_dirty())
        self.url_var = tk.StringVar()
        url = ttk.Entry(row2, textvariable=self.url_var)
        url.pack(side="left", fill="x", expand=True, padx=8)
        url.bind("<KeyRelease>", lambda _e: self._editor_dirty())
        ttk.Label(row2, text="Timeout", style="Panel.TLabel").pack(side="left")
        self.timeout_var = tk.StringVar(value="10")
        ttk.Spinbox(row2, from_=1, to=120, width=5, textvariable=self.timeout_var,
                    command=self._editor_dirty).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="▶ Send", style="Accent.TButton",
                   command=self.run_selected).pack(side="left", padx=(10, 0))

        ttk.Label(tab, text="Headers  (one per line:  Key: value)",
                  style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        self.headers_text = _dark_text(tab, height=5)
        self.headers_text.pack(fill="x")
        self.headers_text.bind("<KeyRelease>", lambda _e: self._editor_dirty())

        ttk.Label(tab, text="Request body", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        self.body_text = _dark_text(tab, height=10)
        self.body_text.pack(fill="both", expand=True)
        self.body_text.bind("<KeyRelease>", lambda _e: self._editor_dirty())

    def _build_assertions_tab(self) -> None:
        tab = ttk.Frame(self.editor, style="Panel.TFrame", padding=10)
        self.editor.add(tab, text="  Assertions  ")
        ttk.Label(tab, text="Assertions checked against the response:",
                  style="Muted.TLabel").pack(anchor="w")

        self.assert_list = tk.Listbox(tab, bg=PANEL, fg=FG, selectbackground="#2b3a63",
                                      relief="flat", bd=6, font=FONT,
                                      activestyle="none", height=8)
        self.assert_list.pack(fill="both", expand=True, pady=(6, 10))

        form = ttk.Frame(tab, style="Panel.TFrame")
        form.pack(fill="x")
        self.assert_kind = ttk.Combobox(form, values=ASSERTION_KINDS,
                                        state="readonly", width=22)
        self.assert_kind.set("status_equals")
        self.assert_kind.grid(row=0, column=0, sticky="w")
        self.assert_kind.bind("<<ComboboxSelected>>", lambda _e: self._sync_assert_form())
        self.assert_target = ttk.Entry(form, width=24)
        self.assert_target.grid(row=0, column=1, padx=6)
        self.assert_target.insert(0, "")
        self.assert_expected = ttk.Entry(form, width=24)
        self.assert_expected.grid(row=0, column=2, padx=6)
        self.assert_expected.insert(0, "200")
        ttk.Label(form, text="path / header", style="Muted.TLabel").grid(row=1, column=1)
        ttk.Label(form, text="expected value", style="Muted.TLabel").grid(row=1, column=2)

        btns = ttk.Frame(tab, style="Panel.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="＋ Add assertion", command=self._add_assertion).pack(side="left")
        ttk.Button(btns, text="Remove selected", style="Danger.TButton",
                   command=self._remove_assertion).pack(side="left", padx=6)

    def _build_response_tab(self) -> None:
        tab = ttk.Frame(self.editor, style="Panel.TFrame", padding=10)
        self.editor.add(tab, text="  Response  ")
        self.response_meta = ttk.Label(tab, text="Run a test to see its response.",
                                       style="Muted.TLabel")
        self.response_meta.pack(anchor="w", pady=(0, 6))
        self.response_text = _dark_text(tab, state="disabled")
        self.response_text.pack(fill="both", expand=True)

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(12, 4))
        bar.pack(side="bottom", fill="x")
        ttk.Separator(self).pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="Ready — add tests and press F5 to run the suite.")
        ttk.Label(bar, textvariable=self.status_var, foreground=MUTED).pack(side="left")
        self.summary_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.summary_var,
                  font=(FONT[0], 10, "bold")).pack(side="right")

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-n>", lambda _e: self.new_suite())
        self.bind("<Control-o>", lambda _e: self.open_suite())
        self.bind("<Control-s>", lambda _e: self.save_suite())
        self.bind("<Control-q>", lambda _e: self.destroy())
        self.bind("<F5>", lambda _e: self.run_all())
        self.bind("<F6>", lambda _e: self.run_selected())
        self.bind("<Escape>", lambda _e: self.stop_run())

    # ---------------- case list helpers ----------------
    def _selected_cases(self) -> list[TestCase]:
        ids = set(self.tree.selection())
        return [c for c in self.cases if c.id in ids]

    def _current_case(self) -> TestCase | None:
        sel = self._selected_cases()
        return sel[0] if sel else None

    def _refresh_tree(self, select_id: str | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for case in self.cases:
            result = self.results.get(case.id)
            verdict = result.verdict if result else "PENDING"
            latency = f"{result.latency_ms:.0f} ms" if result else "—"
            self.tree.insert("", "end", iid=case.id, text=case.name,
                             values=(case.method, verdict, latency), tags=(verdict,))
        if select_id and select_id in self.tree.get_children():
            self.tree.selection_set(select_id)
            self.tree.see(select_id)

    def _on_select(self, _event=None) -> None:
        self._load_editor(self._current_case())

    def _new_case(self) -> None:
        case = TestCase(name=f"Test {len(self.cases) + 1}",
                        url="https://httpbin.org/get",
                        assertions=[Assertion()])
        self.cases.append(case)
        self._refresh_tree(select_id=case.id)
        self._load_editor(case)

    def _duplicate_case(self) -> None:
        src = self._current_case()
        if not src:
            return
        import copy
        clone = copy.deepcopy(src)
        clone.id = TestCase().id
        clone.name = src.name + " (copy)"
        self.cases.append(clone)
        self._refresh_tree(select_id=clone.id)

    def _delete_cases(self) -> None:
        doomed = {c.id for c in self._selected_cases()}
        if not doomed:
            return
        self.cases = [c for c in self.cases if c.id not in doomed]
        for cid in doomed:
            self.results.pop(cid, None)
        self._refresh_tree(select_id=self.cases[0].id if self.cases else None)

    # ---------------- editor binding ----------------
    def _load_editor(self, case: TestCase | None) -> None:
        self._loading_editor = True
        try:
            self.name_var.set(case.name if case else "")
            self.method_var.set(case.method if case else "GET")
            self.url_var.set(case.url if case else "")
            self.timeout_var.set(str(case.timeout_s if case else 10))
            for widget, text in ((self.headers_text,
                                  "\n".join(f"{k}: {v}" for k, v in case.headers.items()) if case else ""),
                                 (self.body_text, case.body if case else "")):
                widget.delete("1.0", "end")
                if text:
                    widget.insert("1.0", text)
            self.assert_list.delete(0, "end")
            if case:
                for a in case.assertions:
                    self.assert_list.insert("end", a.describe())
            self._show_result(self.results.get(case.id) if case else None)
        finally:
            self._loading_editor = False

    def _editor_dirty(self, rename: bool = False) -> None:
        if self._loading_editor:
            return
        case = self._current_case()
        if not case:
            return
        case.name = self.name_var.get().strip() or case.name
        case.method = self.method_var.get()
        case.url = self.url_var.get().strip()
        try:
            case.timeout_s = max(1.0, float(self.timeout_var.get()))
        except ValueError:
            pass
        headers: dict[str, str] = {}
        for line in self.headers_text.get("1.0", "end").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        case.headers = headers
        case.body = self.body_text.get("1.0", "end").rstrip("\n")
        if True:  # keep row in sync on every keystroke
            result = self.results.get(case.id)
            verdict = result.verdict if result else "PENDING"
            self.tree.item(case.id, text=case.name,
                           values=(case.method, verdict,
                                   f"{result.latency_ms:.0f} ms" if result else "—"))

    def _sync_assert_form(self) -> None:
        kind = self.assert_kind.get()
        needs_target = kind in ("json_path_equals", "json_path_exists", "header_equals")
        state = "normal" if needs_target else "disabled"
        self.assert_target.configure(state=state)
        if kind == "json_path_exists":
            self.assert_expected.configure(state="disabled")
        else:
            self.assert_expected.configure(state="normal")

    def _add_assertion(self) -> None:
        case = self._current_case()
        if not case:
            return
        a = Assertion(kind=self.assert_kind.get(),
                      target=self.assert_target.get().strip(),
                      expected=self.assert_expected.get().strip())
        case.assertions.append(a)
        self.assert_list.insert("end", a.describe())

    def _remove_assertion(self) -> None:
        case = self._current_case()
        if not case:
            return
        for index in reversed(self.assert_list.curselection()):
            self.assert_list.delete(index)
            if index < len(case.assertions):
                case.assertions.pop(index)

    # ---------------- running ----------------
    def _start_run(self, cases: list[TestCase]) -> None:
        if self._runner and self._runner.is_alive():
            messagebox.showinfo("Run in progress", "A test run is already in progress.")
            return
        if not cases:
            messagebox.showinfo("Nothing to run", "Add or select at least one test case.")
            return
        self._stop_flag.clear()
        self.stop_btn.configure(state="normal")
        total = len(cases)
        self.status_var.set(f"Running {total} test(s)…")
        self.summary_var.set("")
        for case in cases:
            self.results.pop(case.id, None)
            self.tree.item(case.id, values=(case.method, "RUNNING", "…"), tags=("RUNNING",))

        def on_result(result: TestResult, index: int, count: int) -> None:
            self._queue.put(("result", result, index, count))

        def work() -> None:
            results = run_suite(cases, on_result=on_result,
                                should_stop=self._stop_flag.is_set)
            self._queue.put(("done", results, total))

        self._runner = threading.Thread(target=work, daemon=True)
        self._runner.start()

    def run_all(self) -> None:
        self._editor_dirty()
        self._start_run(list(self.cases))

    def run_selected(self) -> None:
        self._editor_dirty()
        self._start_run(self._selected_cases() or ([self._current_case()] if self._current_case() else []))

    def stop_run(self) -> None:
        self._stop_flag.set()
        self.status_var.set("Stopping after current request…")

    def _poll_queue(self) -> None:
        try:
            while True:
                message = self._queue.get_nowait()
                if message[0] == "result":
                    _, result, index, count = message
                    self.results[result.case.id] = result
                    latency = f"{result.latency_ms:.0f} ms"
                    self.tree.item(result.case.id,
                                   values=(result.case.method, result.verdict, latency),
                                   tags=(result.verdict,))
                    self.status_var.set(f"Running… {index + 1}/{count} — "
                                        f"{result.case.name}: {result.verdict}")
                    if self._current_case() and self._current_case().id == result.case.id:
                        self._show_result(result)
                elif message[0] == "done":
                    _, results, total = message
                    passed = sum(1 for r in results if r.verdict == "PASS")
                    failed = sum(1 for r in results if r.verdict == "FAIL")
                    errors = sum(1 for r in results if r.verdict == "ERROR")
                    stopped = len(results) < total
                    self.status_var.set(
                        ("Stopped. " if stopped else "Run complete. ")
                        + f"{len(results)} executed in "
                        + f"{sum(r.latency_ms for r in results):.0f} ms")
                    self.summary_var.set(f"✓ {passed}   ✗ {failed}   ⚠ {errors}")
                    self.stop_btn.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    # ---------------- response view ----------------
    def _show_result(self, result: TestResult | None) -> None:
        self.response_text.configure(state="normal")
        self.response_text.delete("1.0", "end")
        if result is None:
            self.response_meta.configure(text="Run a test to see its response.")
        elif result.error:
            self.response_meta.configure(text=f"ERROR — {result.error}", foreground=ERROR)
        else:
            color = PASS if result.verdict == "PASS" else (FAIL if result.verdict == "FAIL" else ERROR)
            self.response_meta.configure(
                text=f"{result.verdict}  ·  HTTP {result.status_code}  ·  "
                     f"{result.latency_ms:.0f} ms  ·  "
                     f"{sum(1 for a in result.assertion_results if a.passed)}"
                     f"/{len(result.assertion_results)} assertions passed",
                foreground=color)
            lines = [f"HTTP {result.status_code}", ""]
            for k, v in result.response_headers.items():
                lines.append(f"{k}: {v}")
            lines.append("")
            body = result.response_body
            try:
                body = json.dumps(json.loads(body), indent=2)
            except (ValueError, TypeError):
                pass
            lines.append(body)
            self.response_text.insert("1.0", "\n".join(lines))
        self.response_text.configure(state="disabled")

    # ---------------- suite files & reports ----------------
    def new_suite(self) -> None:
        if not messagebox.askyesno("New suite", "Discard the current suite and start over?"):
            return
        self.cases, self.results = [], {}
        self.suite_path = None
        self.suite_name.set("Untitled suite")
        self._new_case()

    def open_suite(self) -> None:
        path = filedialog.askopenfilename(
            title="Open suite", filetypes=[("Sentinel QA suite", "*.json")])
        if not path:
            return
        try:
            name, cases = load_suite(path)
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.cases, self.results = cases, {}
        self.suite_name.set(name)
        self.suite_path = Path(path)
        self._refresh_tree(select_id=cases[0].id if cases else None)
        self.status_var.set(f"Opened {path}")

    def save_suite(self, ask: bool = False) -> None:
        self._editor_dirty()
        path = self.suite_path
        if ask or path is None:
            chosen = filedialog.asksaveasfilename(
                title="Save suite", defaultextension=".json",
                filetypes=[("Sentinel QA suite", "*.json")])
            if not chosen:
                return
            path = Path(chosen)
        save_suite(self.cases, path, self.suite_name.get())
        self.suite_path = path
        self.status_var.set(f"Saved {path}")

    def export_report(self, fmt: str) -> None:
        if not self.results:
            messagebox.showinfo("No results", "Run some tests first.")
            return
        ordered = [self.results[c.id] for c in self.cases if c.id in self.results]
        chosen = filedialog.asksaveasfilename(
            title=f"Export {fmt.upper()} report", defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}")])
        if not chosen:
            return
        if fmt == "html":
            Path(chosen).write_text(results_to_html(ordered, self.suite_name.get()),
                                    encoding="utf-8")
        else:
            Path(chosen).write_text(results_to_json(ordered, self.suite_name.get()),
                                    encoding="utf-8")
        self.status_var.set(f"Report written to {chosen}")


def main() -> None:
    app = SentinelApp()
    app.mainloop()


if __name__ == "__main__":
    main()
