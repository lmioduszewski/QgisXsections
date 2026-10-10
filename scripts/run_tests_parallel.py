"""Run the XSections test suite in several processes at once (scripts\\run_tests_parallel.bat).

Run it with OSGeo4W's python-qgis (the .bat does), so every worker has QGIS:

    scripts\\run_tests_parallel.bat                          everything, in min(6, CPUs - 1) workers
    scripts\\run_tests_parallel.bat tests.test_ui tests.test_panel     just those (in parallel when more than one)
    scripts\\run_tests_parallel.bat --workers 4               another number of workers
    scripts\\run_tests_parallel.bat --serial                  everything in one process (as scripts\\run_tests.bat)
    scripts\\run_tests_parallel.bat --plan                    print which worker gets what (after listing the
                                                             tests); run no test

Each worker is `python -m unittest -v <its names>` in a process of its own, with the environment of run_tests.bat
(QT_QPA_PLATFORM=offscreen, QT_QPA_FONTDIR, PYTHONDONTWRITEBYTECODE=1; XSECTIONS_REALDATA and XSECTIONS_GPKG passed
through) plus PYTHONUNBUFFERED=1 (its prints stay in order in its log) and a matplotlib config folder of its own (a
copy of the font cache, so no worker ever writes a shared one). Its output goes to worker_<n>.log in a run folder
under the system temp, printed at the start. Every temp file a test makes is per process already (tests/fixtures.py:
RUN_TMP and the QGIS profile come from mkdtemp); the workers' RUN_TMP folders carry the run's tag and the worker's
(XSECTIONS_RUN_TAG) and are removed once the workers have ended (a process cannot remove its own while QGIS still
holds a file of its profile).

Listing: before several workers start, one more process (this script with --list-tests) loads the names with
unittest's own loader and reports every test id, and which modules and classes may be split: those for which loading
each of their classes (module.Class), or each of their tests (module.Class.test_x), gives exactly the tests of the
whole. Tests made at import time count as the loader sees them; a class imported from elsewhere, or tests made by
load_tests, keep their module whole. When the listing fails, nothing is split. At the end every listed test must
have started in a worker (or be explained by a set-up error or skip of its class or module, or a crashed worker):
any other one fails the run ("not run=k"). The listing process starts and ends QGIS as a worker does (the test
modules call start_app at import) and is never waited for without end either: once its line of JSON has come whole
and nothing more for LIST_GRACE s while its output is still open, its exit status is read without waiting (it is
killed, as far as it can be, when it has none EXIT_GRACE s later), and its list is used, with a note; after
LIST_TIMEOUT s it is killed and the run goes on without a list. Its temp folder, too, stays while it has not ended.

Balancing: the longest unit first, each onto the least-loaded worker, by the times remembered from earlier runs
(durations.json next to the run folders; a module never timed is guessed from its number of tests). A module that
would hold up the run on its own (longer than SPLIT_SHARE of one worker's fair share, and than MIN_SPLIT) is split
into its test classes, and such a class into its tests, as the listing allows. Each worker runs its names in
unittest's own order. The times are remembered only from a run whose workers all ended as unittest ends and ran
every listed test (one process: unittest's own run of the names).

A worker has passed only when its exit status is the one `python -m unittest` gives for the result it printed (0 for
OK, 1 for FAILED, 5 when no test ran and none was skipped): a process that prints OK and then dies (say a crash while
QGIS shuts down) fails the run as a crashed worker.

A worker whose output stays open after unittest's final result ("Ran N tests in X s", then OK / FAILED (...) / NO
TESTS RAN) and brings nothing new for RESULT_GRACE s (times its XSECTIONS_TIME_FACTOR) is taken as ended all the same:
once, a worker's python3.exe stayed stuck in Windows' tear-down of the process after unittest's sys.exit (its handle
never signalled, its pipe never closed, taskkill powerless), and the launcher waited for ever. Its exit status is then
read without waiting (GetExitCodeProcess on Windows, poll() elsewhere): when it has one, that is its exit status (the
rules above apply; the summary notes it); when it has none EXIT_GRACE s later, the process is killed (as far as it
can be) and the worker counts as hung after its result, which fails the run (the summary names it, its log and its
PID). The temp folders of a process that has not ended are left in place, and the summary says so.

No worker is waited for without end before its result either. One that has exited without printing unittest's
result while another process (a child of it) holds its output open counts as crashed once nothing has come for
RESULT_GRACE s (times its time factor), as if its pipe had closed. And every worker, the serial re-run too, has a
deadline: WORKER_DEADLINE_K times its planned time (the estimates of its names), at least WORKER_DEADLINE_MIN s, times
its time factor; a worker still running then (stuck in a test, say) is killed and fails the run as timed out (the
summary names it, its log and its PID).

Timing tests (tagged @timing_test, tests/fixtures.py) multiply their time limits and waits by XSECTIONS_TIME_FACTOR,
which the launcher sets for the workers (3 by default; 1 for one process). When several processes ran, every test
that failed is run once more, alone in one process with the factor 1, at the end: the report shows both results. The
serial result decides only for a test tagged @timing_test; any other test that failed in parallel stays a failure.
A run in one process (--serial, --workers 1 or a single name) is never run again: its result stands, as
scripts\\run_tests.bat's would.

The summary's last lines read like unittest's ("Ran N tests in X s", then "OK", "FAILED (...)" or "NO TESTS RAN");
exit status 0 only when everything passed, 5 when no test ran at all (as unittest), 1 otherwise (also after Ctrl+C,
which ends the workers and removes the run's temp folders), 2 when the run is refused (golden files are made only in
one process, by scripts\\run_tests.bat).
"""
from __future__ import annotations

import argparse
import ast
import bisect
import codecs
import datetime
import heapq
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
STATE = Path(tempfile.gettempdir()) / "xsections_tests"        # run folders and durations.json
DURATIONS = STATE / "durations.json"
KEEP_RUNS = 12                                                  # older run folders are removed
MAX_WORKERS = 6
DEFAULT_TIME_FACTOR = 3.0
GUESS_PER_TEST = 0.5                                            # s per test while nothing has been timed
SPLIT_SHARE = 0.6           # a unit longer than this share of a worker's fair load is split (module, class, tests)
MIN_SPLIT = 20.0            # ... and never one shorter than this (s): a worker's start-up alone is about 5 s
GOLDEN_VARS = ("XSECTIONS_MAKE_GOLDEN", "XSECTIONS_REMAKE_GOLDEN")
SEP1, SEP2 = "=" * 70, "-" * 70
FAILED_IMPORT = "unittest.loader._FailedTest."
LIST_FLAG = "--list-tests"                  # this script in the listing process
LIST_MARK = "XSECTIONS-TESTS "              # the listing process's one line of JSON starts with this
LIST_TIMEOUT = 300.0                        # s; the listing takes a few seconds (the imports of the test modules)
LIST_GRACE = 10.0           # s of no output after the listing's whole marked line while its pipe is still open
LIST_LINE_RE = re.compile("^" + re.escape(LIST_MARK) + r"[^\n]*\n", re.M)        # that line, come whole
NO_TESTS_EXIT = 5 if sys.version_info >= (3, 12) else None      # `python -m unittest` when no test ran
RESULT_GRACE = 30.0         # s (times the worker's time factor) of no output after its result while its pipe is open
EXIT_GRACE = 60.0           # s more without an exit status after that: killed, and counted as hung after its result
KILL_WAIT = 5.0             # s to wait for a hung worker's process to end once killed
WORKER_DEADLINE_MIN = 900.0  # s (times the worker's time factor): the least time a worker is given
WORKER_DEADLINE_K = 4.0      # ... or this many times its planned time (its units' estimates), when longer
POLL = 0.25                 # s between two looks at the workers
STILL_ACTIVE = 259          # GetExitCodeProcess's code for a process that has not exited
WAIT_TIMEOUT = 0x102        # WaitForSingleObject: the handle is not signalled (the process has not ended)

# a test starting, in a -v stream: "test_x (tests.test_m.Class.test_x) ... ", or its docstring's line after a newline
START_RE = re.compile(r"^(?P<method>\w+) \((?P<id>[\w.]+)\)(?= \.\.\. |\r?\n)", re.M)
# a status: at the end of the test's line (after " ... "), or alone on a line after what the test printed
STATUS_RE = re.compile(r"(?:^|\.\.\. )(?P<status>ok|FAIL|ERROR|skipped(?: .*)?|expected failure|unexpected success)"
                       r"\r?$", re.M)
# an error outside any test: "setUpClass (tests.test_m.Class) ... ERROR"
FIXTURE_RE = re.compile(r"^(?P<what>setUpClass|tearDownClass|setUpModule|tearDownModule) \((?P<id>[\w.]+)\) "
                        r"\.\.\. ERROR\r?$", re.M)
# a class or module skipped in its set-up (SkipTest): "setUpClass (tests.test_m.Class) ... skipped 'why'"
FIXTURE_SKIP_RE = re.compile(r"^(?P<what>setUpClass|setUpModule) \((?P<id>[\w.]+)\) \.\.\. skipped(?: .*)?\r?$", re.M)
SEP1_RE = re.compile(r"^={70}\r?$", re.M)
RAN_RE = re.compile(r"^Ran (?P<n>\d+) tests? in (?P<s>[\d.]+)s\r?$", re.M)
VERDICT_RE = re.compile(r"^(?P<word>OK|FAILED|NO TESTS RAN)(?: \((?P<infos>[^)]*)\))?\r?$", re.M)
BLOCK_RE = re.compile(r"^(?P<flavour>FAIL|ERROR|UNEXPECTED SUCCESS): (?P<method>\S+) \((?P<id>[\w.]+)\)", re.M)
COUNT_KEYS = ("run", "failures", "errors", "skipped", "expected failures", "unexpected successes")


# ---------------------------------------------------------------------------------------------- the test tree
def discover_modules():
    """The modules `unittest discover -s tests -t .` loads (test*.py in tests and its packages), sorted as it does."""
    found = []
    for folder, dirs, files in os.walk(TESTS):
        dirs[:] = sorted(d for d in dirs if (Path(folder, d) / "__init__.py").is_file())
        for f in files:
            if f.startswith("test") and f.endswith(".py") and f[:-3].isidentifier():
                found.append(".".join(Path(folder, f).relative_to(ROOT).with_suffix("").parts))
    return sorted(found)


def _name(node):
    """The last part of a decorator's or a base's name (`timing_test`, `fixtures.timing_test` -> "timing_test")."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


class ModuleInfo:
    """What a test module's source says (read with ast; nothing is imported): its classes, their bases and test
    methods, and what is tagged @timing_test."""

    def __init__(self, module):
        self.module = module
        self.classes = {}           # name -> {"bases": [names], "tagged": bool, "methods": {name: tagged}}
        path = ROOT.joinpath(*module.split(".")).with_suffix(".py")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self.classes[node.name] = {
                    "bases": [_name(b) for b in node.bases],
                    "tagged": any(_name(d) == "timing_test" for d in node.decorator_list),
                    "methods": {f.name: any(_name(d) == "timing_test" for d in f.decorator_list)
                                for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}}

    def mro(self, cls):
        """`cls` and its bases defined in this module, nearest first."""
        out, todo = [], [cls]
        while todo:
            c = todo.pop(0)
            if c in self.classes and c not in out:
                out.append(c)
                todo.extend(self.classes[c]["bases"])
        return out

    def tests_of(self, cls):
        """The test methods of `cls` (its own and those of its bases here), sorted as unittest sorts them."""
        return sorted({m for c in self.mro(cls) for m in self.classes[c]["methods"] if m.startswith("test")})

    def test_classes(self):
        """{class: its number of tests} for the TestCase classes of this module that have tests."""
        out = {}
        for cls in sorted(self.classes):
            chain = self.mro(cls)
            if any(b.endswith("TestCase") for c in chain for b in self.classes[c]["bases"]) and self.tests_of(cls):
                out[cls] = len(self.tests_of(cls))
        return out

    def is_timing(self, cls, method=None):
        """Is `cls` (or `cls.method`) tagged @timing_test: the class or a base of it here, or the method itself."""
        chain = self.mro(cls)
        if any(self.classes[c]["tagged"] for c in chain):
            return True
        return method is not None and any(self.classes[c]["methods"].get(method) for c in chain)

    def tags(self):
        out = []
        for cls, c in sorted(self.classes.items()):
            if c["tagged"]:
                out.append(cls)
            out.extend(f"{cls}.{m}" for m, tagged in c["methods"].items() if tagged)
        return out


_INFOS = {}


def module_info(module):
    if module not in _INFOS:
        _INFOS[module] = ModuleInfo(module)
    return _INFOS[module]


def split_name(name, modules):
    """A unittest name -> (module, class or None, method or None) for a module of `modules`; else Nones."""
    parts = name.split(".")
    for k in range(len(parts), 0, -1):
        mod = ".".join(parts[:k])
        if mod in modules:
            rest = parts[k:]
            return mod, (rest[0] if rest else None), (rest[1] if len(rest) > 1 else None)
    return None, None, None


def is_timing_test(target, modules):
    mod, cls, method = split_name(target, modules)
    return bool(mod and cls) and module_info(mod).is_timing(cls, method)


# ---------------------------------------------------------------------------------------------- the listing
def _suite_ids(suite):
    out = []
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            out.extend(_suite_ids(t))
        else:
            out.append(t.id())
    return out


def list_names(names, loader=None):
    """(In the listing process.) {"ids": {name: the ids unittest's loader gives for it, in its order}, "parts": {name:
    [[part, its number of tests], ...]}}: a module's classes, or a class's tests (also for each class of a module
    listed so), only where loading each part on its own gives exactly the tests of the whole. A name whose tests do
    not all read <name>.Class.test (or <name>.test) has no parts: a class imported from another module, a class nested
    in another, tests that a load_tests function makes, a module that could not be imported."""
    loader = loader or unittest.TestLoader()
    convert = getattr(sys.modules.get("unittest.main"), "_convert_names", None)      # as `python -m unittest` does
    asked = list(dict.fromkeys(names))
    ids = {}
    for name, loadable in zip(asked, convert(asked) if convert else asked):
        try:
            ids[name] = _suite_ids(loader.loadTestsFromName(loadable))
        except Exception as e:                  # (the worker's unittest stops on it too: it shows there)
            ids[name] = []
            print(f"(could not load {name}: {e!r})")
    parts = {}

    def split(name, got, depth):                # depth 2: a module (ids name.Class.test); 1: a class (name.test)
        tails = [i[len(name) + 1:].split(".") for i in got if i.startswith(name + ".")]
        if not got or len(tails) != len(got) or any(len(t) != depth for t in tails):
            return
        heads = list(dict.fromkeys(t[0] for t in tails))
        try:
            loaded = {h: _suite_ids(loader.loadTestsFromName(f"{name}.{h}")) for h in heads}
        except Exception:
            return
        if sorted(i for h in heads for i in loaded[h]) != sorted(got):
            return
        parts[name] = [[f"{name}.{h}", len(loaded[h])] for h in heads]
        if depth == 2:
            for h in heads:
                split(f"{name}.{h}", loaded[h], 1)

    for name, got in ids.items():
        if got and all(i.startswith(name + ".") for i in got):
            split(name, got, 2 if got[0][len(name) + 1:].count(".") == 1 else 1)
    return {"ids": ids, "parts": parts}


def list_main(names):
    """The listing process: this script run with LIST_FLAG and the names, in the repository (as a worker is)."""
    sys.path[0] = str(ROOT)                     # as `python -m unittest` in the repository: the repository first
    found = list_names(names)
    print("\n" + LIST_MARK + json.dumps(found), flush=True)        # (on a line of its own, whatever was printed)
    return 0


class Listing:
    """What the listing process found: each name's test ids, and the parts each module or class may be split into."""

    def __init__(self, found):
        self.ids = {str(n): [str(i) for i in v] for n, v in found["ids"].items()}
        self.parts = {str(n): [(str(p), int(k)) for p, k in v] for n, v in found.get("parts", {}).items()}
        self.seconds = 0.0

    def all_ids(self):
        return [i for v in self.ids.values() for i in v]

    def count(self, name, default=None):
        return len(self.ids[name]) if name in self.ids else default


def list_tests(names, env, log_path=None, keep=None):
    """Run the listing process for `names`: a Listing, or None (printed why) when it fails. Its output is read as a
    worker's is (a Lister), and it is never waited for without end (no communicate() or wait() without a timeout):
    it has ended when its pipe has closed and its process ended; or, while its pipe is still open, once its marked
    line has come whole and nothing more for LIST_GRACE s (check_open: its exit status read without waiting, or it is
    killed when it has none EXIT_GRACE s later); or LIST_TIMEOUT s after its start it is given up (killed, when it
    has not exited). A whole list is used however it ended (printed with a note). `keep` (a list) gets the Lister: the run's clean-up leaves its temp
    folder in place while its process has not ended."""
    w = Lister(names, os.devnull if log_path is None else log_path, env)
    if keep is not None:
        keep.append(w)
    t0 = time.perf_counter()
    try:
        w.start()
    except OSError as e:
        text, rc = str(e), "none: not started"
        if log_path is not None:
            try:
                Path(log_path).write_text(text, encoding="utf-8", errors="backslashreplace")
            except OSError:
                pass
    else:
        try:
            while not (w.done() or check_open(w, time.perf_counter())):
                if time.perf_counter() - t0 >= LIST_TIMEOUT:
                    w.stopped = True
                    w.stopped_rc = exit_code_now(w.proc)[0]     # (it has exited, something else holds its pipe)
                    if w.stopped_rc is None:
                        w.kill_note = w.kill_hung()
                    break
                w.thread.join(POLL)
        except BaseException:                   # (Ctrl+C: it is ended as the workers are, never waited for long)
            w.kill()
            try:
                w.proc.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                pass
            raise
        if w.stopped:
            text = w.output()[0]
            rc = w.stopped_rc if w.stopped_rc is not None else f"none: stopped after {LIST_TIMEOUT:g} s"
        elif w.hung:
            text, rc = w.text, "none: no exit status after its list"
        else:
            text, rc = w.text, w.returncode
    note = w.note()
    if note:
        print(f"(NOTE: {note})", flush=True)
    line = next((ln for ln in reversed(text.splitlines()) if ln.startswith(LIST_MARK)), None)
    listing = None
    if line is not None:                        # (its whole list, even when the process ended badly after it)
        try:
            listing = Listing(json.loads(line[len(LIST_MARK):]))
        except (ValueError, KeyError, TypeError, AttributeError):
            listing = None
    where = f"; see {log_path}" if log_path else ""
    if listing is None:
        print(f"(the tests could not be listed (exit code {exit_text(rc)}){where}: nothing is split, and the end "
              f"cannot check that every test ran)", flush=True)
        return None
    if isinstance(rc, int) and rc != 0:         # (no exit status: said in the note above)
        print(f"(the listing process ended with exit code {exit_text(rc)} after its list{where})", flush=True)
    listing.seconds = time.perf_counter() - t0
    return listing


# ---------------------------------------------------------------------------------------------- remembered times
def load_durations():
    """{"modules": {name: {"time", "tests"}}, "classes": {...}, "tests": {...} (only tests of a second or more)}."""
    try:
        data = json.loads(DURATIONS.read_text(encoding="utf-8"))
        if isinstance(data, dict) and all(isinstance(data.get(k), dict) for k in ("modules", "classes")):
            data.setdefault("tests", {})
            return data
    except (OSError, ValueError):
        pass
    return {"modules": {}, "classes": {}, "tests": {}}


def save_durations(data):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = DURATIONS.with_name(f"durations.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, DURATIONS)
    except OSError as e:
        print(f"(the times could not be saved to {DURATIONS}: {e})")


def remember(data, kind, name, seconds, tests):
    """Keep a measured time as the mean of the one remembered and this one (one busy run does not swing it)."""
    old = data[kind].get(name)
    t = seconds if not old else 0.5 * (float(old.get("time", seconds)) + seconds)
    data[kind][name] = {"time": round(t, 2), "tests": tests}


# ---------------------------------------------------------------------------------------------- the plan
class Unit:
    """One name a worker is given: a module, a class or a single test (or a name that is none of them)."""

    def __init__(self, name, module=None, cls=None, method=None, estimate=0.0, tests=0):
        self.name, self.module, self.cls, self.method = name, module, cls, method
        self.estimate, self.tests = estimate, tests

    @property
    def kind(self):
        return "test" if self.method else ("class" if self.cls else ("module" if self.module else "name"))


def module_estimates(modules, data, listing=None):
    """{module: seconds}: remembered, else its number of tests (as listed, else as the source shows) times the
    remembered mean per test."""
    known = [(float(v["time"]), int(v["tests"])) for v in data["modules"].values() if v.get("tests")]
    per_test = sum(t for t, _ in known) / sum(n for _, n in known) if known else GUESS_PER_TEST

    def count(m):
        n = listing.count(m) if listing is not None else None
        return n if n is not None else sum(module_info(m).test_classes().values())
    return {m: float(data["modules"][m]["time"]) if m in data["modules"] else max(count(m), 1) * per_test
            for m in modules}


def split_unit(u, data, limit, listing):
    """`u` as it is, or when it is longer than `limit`: a module as its classes, a class as its tests (each part
    split again when it is still longer); only along the parts the listing shows (loaded by unittest's loader, so
    tests made at import time are there), and nothing without a listing."""
    if listing is None or u.estimate <= max(limit, MIN_SPLIT) or u.module is None or u.method:
        return [u]
    found = listing.parts.get(u.name)
    if not found:
        return [u]
    if u.kind == "module":
        total = max(sum(n for _p, n in found), 1)
        parts = [Unit(p, u.module, p.rsplit(".", 1)[1], None,
                      float(data["classes"].get(p, {}).get("time", u.estimate * n / total)), n) for p, n in found]
        if len(parts) == 1:                                 # one class: that class, as its tests if it may be
            parts[0].estimate = u.estimate
            return split_unit(parts[0], data, limit, listing)
    else:
        tests = [p for p, _n in found]
        known = {t: float(data["tests"][t]["time"]) for t in tests if t in data.get("tests", {})}
        rest = max(u.estimate - sum(known.values()), 0.0) / max(len(tests) - len(known), 1)
        parts = [Unit(t, u.module, u.cls, t.rsplit(".", 1)[1], known.get(t, rest), 1) for t in tests]
    if len(parts) < 2:
        return [u]
    return [v for p in parts for v in split_unit(p, data, limit, listing)]


def make_units(names, modules, data, workers, listing=None):
    est = module_estimates(modules, data, listing)
    units = []
    for name in names:
        mod, cls, method = split_name(name, modules)
        if mod is None:
            units.append(Unit(name, estimate=GUESS_PER_TEST))
            continue
        classes = module_info(mod).test_classes()
        listed = listing.count(name) if listing is not None else None
        if cls is None:
            units.append(Unit(name, mod, estimate=est[mod], tests=listed if listed is not None else
                              sum(classes.values())))
            continue
        n = listed if (listed is not None and not method) else classes.get(cls, 1)         # the class's tests
        ct = float(data["classes"].get(f"{mod}.{cls}", {}).get(
            "time", est[mod] * n / max(sum(classes.values()), n, 1)))
        if method:
            ct = float(data.get("tests", {}).get(name, {}).get("time", ct / max(n, 1)))
        units.append(Unit(name, mod, cls, method, ct, 1 if method else n))
    if workers > 1 and len(units) > 1:
        limit = SPLIT_SHARE * sum(u.estimate for u in units) / workers
        units = [v for u in units for v in split_unit(u, data, limit, listing)]
    return units


def assign(units, workers):
    """Longest first, each onto the least-loaded worker; each worker's names then in unittest's order."""
    workers = max(1, min(workers, len(units)))
    heap = [(0.0, i) for i in range(workers)]
    groups = [[] for _ in range(workers)]
    for u in sorted(units, key=lambda u: (-u.estimate, u.name)):
        load, i = heapq.heappop(heap)
        groups[i].append(u)
        heapq.heappush(heap, (load + u.estimate, i))
    for g in groups:
        g.sort(key=lambda u: u.name)
    groups.sort(key=lambda g: -sum(u.estimate for u in g))
    return [g for g in groups if g]


# ---------------------------------------------------------------------------------------------- one process
def printed_result(text):
    """Does `text` hold unittest's final result: its last "Ran N tests in X s" line, then OK, FAILED (...) or NO
    TESTS RAN (as Result reads it)?"""
    ran = None
    for ran in RAN_RE.finditer(text):
        pass
    return ran is not None and VERDICT_RE.search(text, ran.end()) is not None


_KERNEL32 = None


def _kernel32():
    """kernel32's GetExitCodeProcess and WaitForSingleObject, with their argument types (a loader of our own, so
    ctypes.windll's shared functions are left as they are)."""
    global _KERNEL32
    if _KERNEL32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.GetExitCodeProcess.restype = wintypes.BOOL
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.WaitForSingleObject.restype = wintypes.DWORD
        _KERNEL32 = k
    return _KERNEL32


def _win_handle(proc):
    """The process handle of a Popen on Windows (an int), else None."""
    h = getattr(proc, "_handle", None) if os.name == "nt" else None
    return int(h) if isinstance(h, int) and not getattr(h, "closed", False) else None


def exit_code_now(proc):
    """(exit status, has the process ended), read without waiting; (None, False) while it has no exit status.
    poll() gives one only once the process has ended (on Windows: once its handle is signalled). On Windows a
    process's exit code is set when it exits, and the kernel's tear-down of it can stay stuck after that (its handle
    never signalled, its pipes open): there GetExitCodeProcess reads it all the same; STILL_ACTIVE (259) means it has
    not exited."""
    rc = proc.poll()
    if rc is not None:
        return rc, not process_alive(proc)
    h = _win_handle(proc)
    if h is None:
        return None, False
    try:
        import ctypes
        from ctypes import wintypes
        code = wintypes.DWORD()
        if _kernel32().GetExitCodeProcess(h, ctypes.byref(code)) and code.value != STILL_ACTIVE:
            return int(code.value), False
    except (OSError, AttributeError, ValueError):
        pass
    return None, False


def process_alive(proc):
    """Has the process not ended yet (on Windows: its handle is not signalled, whatever its exit code says)?"""
    if proc is None:
        return False
    h = _win_handle(proc)
    if h is not None:
        try:
            return _kernel32().WaitForSingleObject(h, 0) == WAIT_TIMEOUT
        except (OSError, AttributeError, ValueError):
            pass
    return proc.poll() is None


def deadline_for(planned, factor):
    """The seconds a worker planned at `planned` s is given from its start (check_deadline), at time factor `factor`."""
    return max(WORKER_DEADLINE_MIN, WORKER_DEADLINE_K * planned) * factor


class Worker:
    """One `python -m unittest -v <names>` process. Its output is copied to its log as it comes, each piece noted
    with the time it arrived: a test starts when its line reaches the pipe and ends when its status does. The text
    read so far is there for run_all (output()) while the pipe is still open."""

    cut_without_result = True       # check_open: exited without its result, its output held open -> taken as ended

    def __init__(self, label, units, log_path, env):
        self.label, self.units, self.log_path, self.env = label, units, Path(log_path), env
        self.names = [u.name for u in units]
        self.cmd = [sys.executable, "-m", "unittest", "-v", *self.names]
        self.tag = env.get("XSECTIONS_RUN_TAG", "")             # its processes' RUN_TMP: xsec_run_<tag>...
        self.text = ""
        self.ends, self.times = [], []          # text offset where each piece ends, its arrival time
        self.proc = self.thread = self.result = None
        self.t0 = self.t1 = 0.0
        self.returncode = None
        self._lock = threading.Lock()
        self._parts = []                        # the decoded pieces so far
        self._ended = False                     # its pipe closed and its process ended (as usual)
        self.last_output = 0.0                  # when its last piece arrived (its start while none has)
        try:
            factor = float(env.get("XSECTIONS_TIME_FACTOR", "") or 1.0)
        except ValueError:
            factor = 1.0
        factor = factor if factor > 0 else 1.0
        self.result_grace = RESULT_GRACE * factor
        self.exit_grace = EXIT_GRACE
        # its deadline (check_deadline): killed and timed out when still running that long after its start
        self.planned = sum(u.estimate for u in units)
        self.deadline = deadline_for(self.planned, factor)
        self.timed_out = False
        # taken as ended while its output was still open (run_all): how its exit status was read ("windows": the
        # process had not ended, its exit code had been set; "ended": it had ended, something else held its pipe),
        # or hung (no exit status EXIT_GRACE s after that), and what killing it gave
        self.cut_off = False
        self.exit_read = None
        self.hung = False
        self.kill_note = None
        self.waiting_since = None               # when it was first found with its result and no exit status
        self.who, self.printed = f"worker {label}", "its result"        # (in what is printed of it)

    def complete(self, text):
        """Does its output hold all it is to print (check_open): unittest's final result."""
        return printed_result(text)

    def start(self):
        self.t0 = self.last_output = time.perf_counter()
        self.proc = subprocess.Popen(self.cmd, cwd=str(ROOT), env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False) or "utf-8")(errors="replace")
        size = 0
        with open(self.log_path, "wb") as log:
            while True:
                chunk = self.proc.stdout.read(65536)
                if not chunk:
                    break
                now = time.perf_counter()
                log.write(chunk)
                log.flush()
                piece = decoder.decode(chunk)
                size += len(piece)
                with self._lock:
                    self._parts.append(piece)
                    self.ends.append(size)
                    self.times.append(now)
                    self.last_output = now
            with self._lock:
                self._parts.append(decoder.decode(b"", final=True))
        self.proc.stdout.close()                # (its end of the pipe: closed at its end)
        rc = self.proc.wait()
        with self._lock:                        # (not once run_all has taken it as ended: what it found stands)
            if not self.cut_off:
                self.text = "".join(self._parts)
                self.returncode = rc
                self.t1 = time.perf_counter()
            self._ended = True

    def output(self):
        """(the text read so far, when its last piece arrived)."""
        with self._lock:
            return "".join(self._parts), self.last_output

    def done(self):
        return self.thread is not None and not self.thread.is_alive()

    def take_as_ended(self, text, last, rc, how):
        """Take the worker as ended with the output read so far: with exit status `rc` (read as `how`), or hung
        (`rc` None). False when its pipe closed and its process ended meanwhile (the usual end stands), except for a
        hung one (it did not end as unittest ends: killing it does not change that)."""
        with self._lock:
            if self._ended and rc is not None:
                return False
            self.cut_off = True
            self.text, self.t1, self.returncode = text, last, rc
            self.exit_read, self.hung = (how, False) if rc is not None else (None, True)
            return True

    def kill(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:                     # (a process Windows is still tearing down: access denied)
                pass

    def kill_hung(self):
        """Try to end a hung worker's process; what it gave, in words."""
        try:
            self.proc.kill()
        except OSError as e:
            return f"killing it failed ({e})"
        deadline = time.perf_counter() + KILL_WAIT
        while time.perf_counter() < deadline:
            if not process_alive(self.proc):
                return "it was killed"
            time.sleep(0.1)
        return f"it was killed, but had not ended {KILL_WAIT:g} s later"

    def time_at(self, offset):
        """When the text at `offset` arrived."""
        i = bisect.bisect_right(self.ends, offset)
        return self.times[i] if i < len(self.times) else (self.t1 or time.perf_counter())


class Lister(Worker):
    """The listing process (this script with LIST_FLAG and the names), read as a worker is: its output is complete
    once its marked line of JSON has come whole (the last thing it prints); LIST_GRACE s of quiet after that. It has
    no deadline and is not taken as ended without its list: list_tests gives it up LIST_TIMEOUT s after its start."""

    cut_without_result = False

    def __init__(self, names, log_path, env):
        super().__init__("list", [], log_path, env)
        self.cmd = [sys.executable, str(Path(__file__).resolve()), LIST_FLAG, *names]
        self.who, self.printed = "the listing process", "its list"
        self.result_grace = LIST_GRACE
        self.deadline = None                    # (unused: LIST_TIMEOUT)
        self.stopped = False                    # given up LIST_TIMEOUT s after its start (killed if it had not exited)
        self.stopped_rc = None                  # ... its exit status then, when it had one

    def complete(self, text):
        return LIST_LINE_RE.search(text) is not None

    def note(self):
        """How it ended, when that was not as a process ends (its pipe closed, its process ended), in words; else ""."""
        pid = getattr(self.proc, "pid", "?")
        if self.stopped and self.stopped_rc is not None:
            return (f"the listing process (PID {pid}) had exited (exit code {exit_text(self.stopped_rc)}), but its "
                    f"output was still open {LIST_TIMEOUT:g} s after its start (held by a process it started?); it "
                    f"was not waited for any longer")
        if self.stopped:
            return (f"the listing process (PID {pid}) had not ended {LIST_TIMEOUT:g} s after its start; "
                    f"{self.kill_note or 'it was not killed'}")
        if self.hung:
            return (f"the listing process (PID {pid}) printed its list, then nothing for {self.result_grace:g} s with "
                    f"its output still open, and still had no exit status {self.exit_grace:g} s later; "
                    f"{self.kill_note or 'it was not killed'}; its list is used")
        if self.exit_read == "windows":
            return (f"the listing process (PID {pid}) did not end after its list (Windows); exit code "
                    f"{exit_text(self.returncode)} used")
        if self.exit_read == "ended":
            return (f"the listing process (PID {pid}) had ended, but its output stayed open after its list (held by a "
                    f"process it started?); exit code {exit_text(self.returncode)} used")
        return ""


class Result:
    """What one worker's -v stream says: each test with its status and times, the counts, the error listing."""

    def __init__(self, w):
        text = w.text
        ran = list(RAN_RE.finditer(text))
        self.finished = bool(ran)
        end = ran[-1].start() if ran else len(text)
        starts, seen = [], set()
        for m in START_RE.finditer(text, 0, end):
            tid = m.group("id")
            if tid.endswith("." + m.group("method")) and tid not in seen:       # (a re-written line is not a start)
                seen.add(tid)
                starts.append(m)
        # the error listing (printErrors) begins at the first separator line after the last test's line
        sep = SEP1_RE.search(text, starts[-1].end() if starts else 0, end)
        self.listing_at = sep.start() if sep else end
        self.listing = text[self.listing_at:end].rstrip()
        if self.listing.endswith(SEP2):                         # (the line unittest writes before "Ran ...")
            self.listing = self.listing[:-len(SEP2)].rstrip()
        # errors outside any test (a class's or module's set-up or tear-down): their lines in the stream, and their
        # entries in the listing (after an "expected failure" unittest 3.12 writes such a line as a bare "ERROR")
        found_fixtures = list(FIXTURE_RE.finditer(text, 0, end))
        found_skips = list(FIXTURE_SKIP_RE.finditer(text, 0, end))     # (a class or module skipped in its set-up)
        fixture_lines = [(m.start(), m.end()) for m in found_fixtures + found_skips]
        self.fixture_errors = list(dict.fromkeys(
            [(m.group("what"), m.group("id")) for m in found_fixtures] +
            [(b.group("method"), b.group("id")) for b in BLOCK_RE.finditer(self.listing)
             if b.group("method") in ("setUpClass", "tearDownClass", "setUpModule", "tearDownModule")]))
        self.fixture_skips = list(dict.fromkeys((m.group("what"), m.group("id")) for m in found_skips))
        self.tests = []             # [id, status, start, end, gap before it, n FAIL, n ERROR]
        prev = None
        for k, m in enumerate(starts):
            stop = starts[k + 1].start() if k + 1 < len(starts) else self.listing_at
            found = [s for s in STATUS_RE.finditer(text, m.end(), stop)
                     if not any(a <= s.start() < b for a, b in fixture_lines)]
            # a failed subtest has a line of its own ("  test_x (id) (i=1) ... FAIL"); the test's own status is the
            # first other one (a later bare status belongs to a set-up or tear-down error: see above)
            subs, own = [], []
            for s in found:
                indented = text.startswith("  ", text.rfind("\n", 0, s.start()) + 1)
                (subs if indented and s.group(0).startswith("... ") else own).append(s)
            own = own[:1]
            # its start: when its line reached the pipe; its end: when its status word did
            t_start = w.time_at(m.start())
            last = max(own + subs, key=lambda s: s.start(), default=None)
            t_end = w.time_at(last.start("status")) if last is not None else w.time_at(stop)
            nf = sum(s.group("status") == "FAIL" for s in subs)
            ne = sum(s.group("status") == "ERROR" for s in subs)
            if own:
                status = own[0].group("status").split(" ")[0]
                nf += status == "FAIL"
                ne += status == "ERROR"
            elif subs:
                status = "FAIL" if nf else "ERROR"
            else:
                status = "crashed" if (not self.finished and k + 1 == len(starts)) else "no status"
            if status in ("ok", "skipped", "expected") and (nf or ne):
                status = "FAIL" if nf else "ERROR"
            self.tests.append([m.group("id"), status, t_start, t_end, 0.0 if prev is None else max(0.0, t_start - prev),
                               nf, ne])
            prev = t_end
        self.startup = (self.tests[0][2] - w.t0) if self.tests else 0.0
        t_ran = w.time_at(ran[-1].start()) if ran else (w.t1 or prev or w.t0)
        self.tail = max(0.0, t_ran - prev) if prev is not None else 0.0
        self.counts = dict.fromkeys(COUNT_KEYS, 0)
        self.verdict = "no result"
        if ran:
            self.counts["run"] = int(ran[-1].group("n"))
            v = VERDICT_RE.search(text, ran[-1].end())
            if v:
                self.verdict = v.group(0).strip()
                for part in (v.group("infos") or "").split(","):
                    if "=" in part:
                        key, val = part.strip().split("=", 1)
                        self.counts[key] = self.counts.get(key, 0) + int(val)
        self.names = w.names

    def expected_exit(self):
        """The exit status `python -m unittest` gives for the result this stream printed (Python 3.12: 5 when no test
        ran and none was skipped, even after a set-up error; else 0 when it printed OK, 1 when FAILED)."""
        if NO_TESTS_EXIT is not None and self.counts["run"] == 0 and self.counts["skipped"] == 0:
            return NO_TESTS_EXIT
        return 0 if self.verdict.startswith(("OK", "NO TESTS RAN")) else 1

    def exit_ok(self, rc):
        """Did the process end as unittest ends after printing its result? Not when it printed none, nor when its
        exit status disagrees with what it printed (it printed OK, then crashed: in QGIS's or Qt's shutdown, say)."""
        return self.finished and self.verdict != "no result" and rc == self.expected_exit()

    def explains(self, tid):
        """Does a set-up error or skip of the class or module of `tid` explain why it never started here?"""
        return any(tid.startswith(fid + ".") for what, fid in self.fixture_errors + self.fixture_skips
                   if what in ("setUpClass", "setUpModule"))

    def target_of(self, tid):
        """The name to run again for a failed id: a module that could not be imported is its unit's name."""
        if tid.startswith(FAILED_IMPORT):
            last = tid[len(FAILED_IMPORT):]
            return next((n for n in self.names if n.split(".")[-1] == last or n == last), last)
        return tid

    def failing(self):
        """[{target, id, label, nf, ne}]: each failed test, each class or module whose set-up or tear-down failed, a
        module that could not be imported, and the test a crash stopped in."""
        out = []
        for tid, status, _s, _e, _g, nf, ne in self.tests:
            if status in ("FAIL", "ERROR", "unexpected", "crashed"):
                label = "import ERROR" if tid.startswith(FAILED_IMPORT) else status
                out.append(dict(target=self.target_of(tid), id=tid, label=label, nf=nf, ne=ne))
        for what, fid in self.fixture_errors:
            out.append(dict(target=fid, id=fid, label=f"{what} ERROR", nf=0, ne=1))
        return out

    def block_for(self, tid):
        """The listing's entry (header and traceback) for the id `tid`, or ""."""
        for b in BLOCK_RE.finditer(self.listing):
            if b.group("id") == tid:
                nxt = SEP1_RE.search(self.listing, b.end())
                return self.listing[b.start(): nxt.start() if nxt else len(self.listing)].rstrip()
        return ""


# ---------------------------------------------------------------------------------------------- running
def worker_env(factor, mpl_dir, tag=""):
    env = dict(os.environ)
    env.update(QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    env.pop("XSECTIONS_RUN_TAG", None)
    if tag:
        env["XSECTIONS_RUN_TAG"] = tag              # tests/fixtures.py: its RUN_TMP is xsec_run_<tag>...
    env.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    env.pop("XSECTIONS_TIME_FACTOR", None)
    if factor != 1.0:
        env["XSECTIONS_TIME_FACTOR"] = f"{factor:g}"
    if mpl_dir is not None:
        env["MPLCONFIGDIR"] = str(mpl_dir)
    return env


def matplotlib_seed():
    """The user's matplotlib config and cache folders, the font cache made first when it is missing or stale (here,
    in this one process), so each worker starts from a copy of it; None when matplotlib cannot be imported."""
    try:
        import matplotlib
        from matplotlib import font_manager  # noqa: F401  (reads the font cache; builds it when it is missing)
        return [Path(matplotlib.get_configdir()), Path(matplotlib.get_cachedir())]
    except Exception as e:                   # (the workers then use matplotlib's own folder, as a serial run does)
        print(f"(matplotlib not prepared: {e})")
        return None


def mpl_folder(run_dir, label, seed):
    """A worker's own MPLCONFIGDIR: the font cache, matplotlibrc and stylelib of the user's folders copied."""
    if not seed:
        return None
    dest = run_dir / f"mpl_{label}"
    dest.mkdir(exist_ok=True)
    for src in dict.fromkeys(seed):
        try:
            for p in src.iterdir():
                if p.is_file() and (p.name.startswith("fontlist") or p.name == "matplotlibrc"):
                    shutil.copy2(p, dest / p.name)
                elif p.is_dir() and p.name == "stylelib" and not (dest / p.name).exists():
                    shutil.copytree(p, dest / p.name)
        except OSError:
            pass
    return dest


def run_temp(tag):
    """The RUN_TMP folders of the processes started with XSECTIONS_RUN_TAG `tag` (or a tag that begins with it)."""
    return sorted(p for p in Path(tempfile.gettempdir()).glob(f"xsec_run_{tag}*") if p.is_dir()) if tag else []


def remove_run_temp(tag, keep=()):
    """Remove the RUN_TMP folders of this run's processes (ended): a test process cannot remove its own while QGIS
    still holds a file of its profile (symbology-style.db) at exit. Those of the tags in `keep` stay (a process that
    has not ended may still use them)."""
    n = 0
    kept = [f"xsec_run_{k}" for k in keep]
    for p in run_temp(tag):
        if not any(p.name.startswith(k) for k in kept):
            shutil.rmtree(p, ignore_errors=True)
            n += not p.exists()
    return n


def held_temp(workers):
    """[(worker, its RUN_TMP folders)] for each worker whose process has not ended (hung, or stuck in Windows'
    tear-down after its exit status was read): its folders are left in place."""
    return [(w, run_temp(w.tag)) for w in workers if w.proc is not None and process_alive(w.proc)]


def held_lines(held):
    """The summary's lines on the temp folders left in place."""
    out = []
    for w, paths in held:
        pid = getattr(w.proc, "pid", "?")
        out.append(f"Temp folders of {w.who} left in place: its process (PID {pid}) has not ended "
                   f"({len(paths)} folder(s){': ' + ', '.join(str(p) for p in paths) if paths else ''}); remove "
                   f"them once it has (after a restart, if need be).")
    return out


def prune_runs():
    try:
        runs = sorted((p for p in STATE.iterdir() if p.is_dir() and p.name.startswith("run_")),
                      key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for p in runs[:-KEEP_RUNS]:
        shutil.rmtree(p, ignore_errors=True)


def exit_text(rc):
    """An exit status as Windows shows a crash's too (3221225477 -> "3221225477 = 0xC0000005")."""
    if isinstance(rc, int) and not 0 <= rc <= 255:
        return f"{rc} = 0x{rc & 0xFFFFFFFF:08X}"
    return str(rc)


def late_exit_note(w):
    """The summary's note on a worker whose exit status was read while its output was still open, or ""."""
    if w.exit_read and not printed_result(w.text):          # (check_open: it exited without unittest's result)
        return (f"worker {w.label}'s process ended (exit code {exit_text(w.returncode)}) without unittest's result, "
                f"its output held open (by a process it started?)")
    if w.exit_read == "windows":
        return (f"worker {w.label}'s process did not end after its result (Windows); exit code "
                f"{exit_text(w.returncode)} used")
    if w.exit_read == "ended":
        return (f"worker {w.label}'s output stayed open after its result although its process had ended (held by a "
                f"process it started?); exit code {exit_text(w.returncode)} used")
    return ""


def hung_text(w):
    """What the summary says of a worker that hung after its result."""
    return (f"WORKER {w.label} HUNG AFTER ITS RESULT ({w.result.verdict}): its process (PID "
            f"{getattr(w.proc, 'pid', '?')}) printed unittest's result, then nothing for "
            f"{w.result_grace:g} s, and still had no exit status {w.exit_grace:g} s later; "
            f"{w.kill_note or 'it was not killed'}. It counts as failed whatever it printed. See {w.log_path}")


def timed_out_text(w):
    """What the summary says of a worker still running at its deadline (check_deadline)."""
    last = w.result.tests[-1][0] if w.result is not None and w.result.tests else "(none had started)"
    return (f"WORKER {w.label} TIMED OUT: its process (PID {getattr(w.proc, 'pid', '?')}) was still running "
            f"{w.deadline:g} s after its start (its deadline: {WORKER_DEADLINE_K:g} x its planned {w.planned:.0f} s, "
            f"at least {WORKER_DEADLINE_MIN:g} s, times its time factor); {w.kill_note}. The last test it started: "
            f"{last}. See {w.log_path}")


def worker_state(w):
    """A worker's result in a few words: its verdict, or how it ended when that was not as unittest ends."""
    r = w.result
    if w.timed_out:
        return f"TIMED OUT after {w.deadline:g} s (PID {getattr(w.proc, 'pid', '?')}; {w.kill_note})"
    if w.hung:
        return (f"{r.verdict}, but HUNG after its result: no exit status (PID {getattr(w.proc, 'pid', '?')}; "
                f"{w.kill_note or 'not killed'})")
    if not r.finished:
        held = " (its output was still open: held by a process it started?)" if w.exit_read else ""
        return f"ended without a result (exit code {exit_text(w.returncode)}){held}"
    late = f" ({late_exit_note(w)})" if w.exit_read else ""
    if not r.exit_ok(w.returncode):
        return (f"{r.verdict}, but exit code {exit_text(w.returncode)} (unittest ends with {r.expected_exit()} after "
                f"that): it ended badly after its result{late}")
    return r.verdict + late


def check_open(w, now):
    """For a worker (or the Lister) whose output is still open: True once it is to be taken as ended (take_as_ended
    has been called). That is when its output holds unittest's final result (the Lister's: its whole list) and
    nothing new has come for its result_grace: then its exit status is read without waiting and, when it has one,
    taken; when it still has none exit_grace s later, it is killed and taken as hung after its result. A worker (not
    the Lister: cut_without_result) quiet that long without its result whose process has an exit status (it has
    exited, a process it started holding its output) is taken as ended with it: a crash without a result. New output
    on the way starts it all again."""
    if now - w.last_output < w.result_grace:
        w.waiting_since = None
        return False
    text, last = w.output()
    if now - last < w.result_grace:
        w.waiting_since = None
        return False
    if not w.complete(text):
        w.waiting_since = None
        if w.cut_without_result:
            rc, ended = exit_code_now(w.proc)
            if rc is not None:
                return w.take_as_ended(text, last, rc, "ended" if ended else "windows")
        return False
    rc, ended = exit_code_now(w.proc)
    if rc is not None:
        return w.take_as_ended(text, last, rc, "ended" if ended else "windows")
    if w.waiting_since is None:
        w.waiting_since = now
        print(f"  ({w.who} printed {w.printed} {now - last:.0f} s ago and its process (PID "
              f"{getattr(w.proc, 'pid', '?')}) has not ended: waiting up to {w.exit_grace:g} s more)", flush=True)
        return False
    if now - w.waiting_since < w.exit_grace:
        return False
    w.kill_note = w.kill_hung()
    return w.take_as_ended(text, last, None, None)


def check_deadline(w, now):
    """For a worker whose pipe has not closed: True once it is still running `w.deadline` s after its start (its
    result or not; the Lister has none): then it is killed (when its process is alive; else it had exited, another
    process holding its output) and taken as ended, timed out, with the output read so far. False when it ended
    meanwhile on its own (the usual end stands); once killed, it stays timed out whatever its end gives."""
    if w.deadline is None or w.done() or now - w.t0 < w.deadline:
        return False
    with w._lock:
        if w._ended:                            # (its pipe closed and its process ended meanwhile)
            return False
        w.cut_off = True                        # (from here its pump leaves text, exit status and end as found here)
    text, _last = w.output()
    rc, _ended = exit_code_now(w.proc)
    if process_alive(w.proc):
        w.kill_note = w.kill_hung()
    else:
        w.kill_note = f"it had already exited (exit code {exit_text(rc)}); another process held its output"
    with w._lock:
        w.text, w.t1, w.returncode, w.timed_out = text, now, rc, True
    return True


def run_all(workers, what):
    """Start the workers and wait until each has ended: its pipe closed and its process ended, or taken as ended
    after its result or without one (check_open), or at its deadline (check_deadline). Each one's Result is made as
    it ends."""
    for w in workers:
        w.start()
    try:
        pending = list(workers)
        while pending:
            time.sleep(POLL)
            now = time.perf_counter()
            for w in [w for w in pending if w.done() or check_open(w, now) or check_deadline(w, now)]:
                pending.remove(w)
                w.result = r = Result(w)
                n = r.counts["run"]
                print(f"  {what} {w.label} done: {n} test{'' if n == 1 else 's'} in {w.t1 - w.t0:.1f} s, "
                      f"{worker_state(w)}", flush=True)
    except KeyboardInterrupt:
        for w in workers:
            w.kill()
        for w in workers:                   # (until each has ended: its files in the run's temp folder are let go)
            if w.proc is not None:
                try:
                    w.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        raise


def measured_times(ws, modules):
    """({module: [s, tests]}, {module.Class: [s, tests]}, {test id: s}): each test's own time plus the wait before it
    (its class's set-up), the last one's tear-down too; a worker's start-up beyond the quickest worker's (the set-up
    of its first class) goes to its first test."""
    base = min((w.result.startup for w in ws if w.result.tests), default=0.0)
    per_module, per_class, per_test = {}, {}, {}
    for w in ws:
        r = w.result
        for k, (tid, _status, s, e, gap, _nf, _ne) in enumerate(r.tests):
            mod, cls, _m = split_name(tid, modules)
            if mod is None:
                continue
            dt = (e - s) + gap + (r.tail if k == len(r.tests) - 1 else 0.0) + (r.startup - base if k == 0 else 0.0)
            per_test[tid] = dt
            for d, key in ((per_module, mod), (per_class, f"{mod}.{cls}")):
                d.setdefault(key, [0.0, 0])
                d[key][0] += dt
                d[key][1] += 1
    return per_module, per_class, per_test


RESCUABLE = ("FAIL", "ERROR", "setUpClass ERROR")


def decide(totals, failing, rerun, crashed, modules):
    """(ok, the final counts, the targets counted as passed). A target that failed in parallel counts as passed only
    when it is tagged @timing_test (the test, its class or a base) and passed when run again alone; any other failure
    stands, whatever its re-run gave; a crashed worker fails the run."""
    rescued = {f["target"] for f in failing}
    for f in failing:
        if not (f["label"] in RESCUABLE and rerun.get(f["target"]) == "ok" and is_timing_test(f["target"], modules)):
            rescued.discard(f["target"])
    final = dict(totals)
    for f in failing:
        if f["target"] in rescued:
            final["failures"] -= f["nf"]
            final["errors"] -= f["ne"]
    final["errors"] += crashed
    ok = (crashed == 0 and final["failures"] <= 0 and final["errors"] <= 0 and final["unexpected successes"] == 0
          and all(f["target"] in rescued for f in failing))
    final["failures"], final["errors"] = max(final["failures"], 0), max(final["errors"], 0)
    return ok, final, rescued


def not_run(listing, ws, crashed):
    """([the listed ids that started in no worker, with nothing to explain it], the number of listed ids that did not
    start because a set-up error or skip of their class or module, or a crashed worker, explains it)."""
    started = {t[0] for w in ws for t in w.result.tests}
    lost = [n for w in crashed for n in w.names]            # (the rest of a crashed worker's names: counted as crashed)
    missing, explained = {}, 0
    for tid in listing.all_ids():
        if tid in started:
            continue
        if any(w.result.explains(tid) for w in ws) or any(tid == n or tid.startswith(n + ".") for n in lost):
            explained += 1
        else:
            missing[tid] = None
    return list(missing), explained


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the XSections tests in several processes at once.")
    ap.add_argument("names", nargs="*", help="unittest names (modules, classes or tests); none: the whole suite")
    ap.add_argument("--workers", type=int, default=None,
                    help=f"number of worker processes (default min({MAX_WORKERS}, CPUs - 1))")
    ap.add_argument("--serial", action="store_true", help="one process, like scripts\\run_tests.bat")
    ap.add_argument("--time-factor", type=float, default=None,
                    help=f"XSECTIONS_TIME_FACTOR for the workers (default {DEFAULT_TIME_FACTOR:g}; 1 in one process)")
    ap.add_argument("--no-rerun", action="store_true", help="do not run the failed tests again, serially")
    ap.add_argument("--plan", action="store_true", help="print which worker gets what (after listing the tests), "
                                                        "and stop")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    modules = discover_modules()
    names = list(dict.fromkeys(args.names)) or modules
    if args.workers is not None and args.workers < 1:
        ap.error("--workers must be at least 1")
    workers = 1 if (args.serial or len(names) == 1) else (args.workers or min(MAX_WORKERS, max(1, (os.cpu_count()
                                                                                                  or 2) - 1)))
    try:
        if args.time_factor is not None:
            factor = args.time_factor
        elif os.environ.get("XSECTIONS_TIME_FACTOR", "").strip():
            factor = float(os.environ["XSECTIONS_TIME_FACTOR"])
        else:
            factor = 1.0 if workers == 1 else DEFAULT_TIME_FACTOR
    except ValueError:
        factor = float("nan")
    if not factor > 0:
        ap.error("the time factor (--time-factor or XSECTIONS_TIME_FACTOR) must be a number above 0")
    golden = [v for v in GOLDEN_VARS if os.environ.get(v, "").strip()]
    if golden and workers > 1:
        print(f"Refused: {' and '.join(golden)} set. Golden files are made only in one process, by "
              f"scripts\\run_tests.bat, and only with the user's approval.")
        return 2

    data = load_durations()
    if args.plan:
        listing = None
        if workers > 1:                         # (its process's temp folder carries a tag of its own: removed)
            tag = f"plan_{os.getpid()}_"
            listers = []
            try:
                listing = list_tests(names, worker_env(1.0, None, tag), keep=listers)
            finally:                            # (but not while its process has not ended)
                held = held_temp(listers)
                remove_run_temp(tag, keep=[w.tag for w, _p in held])
                for line in held_lines(held):
                    print(line, flush=True)
        units = make_units(names, modules, data, workers, listing)
        groups = assign(units, workers) if workers > 1 else [units]       # one process: the order given
        print(f"{len(groups)} worker(s), XSECTIONS_TIME_FACTOR={factor:g}; times from {DURATIONS}"
              f"{'' if DURATIONS.is_file() else ' (none yet: guessed from the numbers of tests)'}")
        if listing is not None:
            print(f"{len(listing.all_ids())} tests listed by unittest's loader in {listing.seconds:.1f} s; split "
                  f"along the parts it shows")
        for i, g in enumerate(groups, 1):
            est = sum(u.estimate for u in g)
            print(f"worker {i}: about {est:.0f} s (deadline {deadline_for(est, factor):.0f} s)")
            for u in g:
                print(f"  {u.estimate:7.1f} s  {u.name}")
        tags = [f"{m}.{t}" for m in modules for t in module_info(m).tags()]
        print(f"tagged @timing_test: {len(tags)}")
        for t in tags:
            print(f"  {t}")
        return 0

    STATE.mkdir(parents=True, exist_ok=True)
    prune_runs()
    run_dir = Path(tempfile.mkdtemp(prefix=f"run_{datetime.datetime.now():%Y%m%d_%H%M%S}_", dir=STATE))
    seed = matplotlib_seed()
    t_start = time.perf_counter()
    realdata = "set" if os.environ.get("XSECTIONS_REALDATA") else "not set"
    print(f"Run folder (a log per worker): {run_dir}", flush=True)
    tag = run_dir.name + "_"                    # the run's; each process's begins with it (list_, w<n>_, rerun_)
    everyone = []                               # the workers started (their temp folders stay until they end)
    listers = []                                # the listing process (its temp folder too; it is no worker)
    try:
        # ---- the tests unittest's loader finds for the names: the parts a module or class may be split into, and
        # at the end the check that every one of them ran (not needed in one process: that is unittest's own run)
        listing = None
        if workers > 1:
            listing = list_tests(names, worker_env(1.0, mpl_folder(run_dir, "list", seed), tag + "list_"),
                                 run_dir / "list.log", keep=listers)
            if listing is not None:
                print(f"Listed {len(listing.all_ids())} tests (unittest's loader, one process) in "
                      f"{listing.seconds:.1f} s", flush=True)
        units = make_units(names, modules, data, workers, listing)
        groups = assign(units, workers) if workers > 1 else [units]       # one process: the order given
        print(f"XSections tests: {sum(len(g) for g in groups)} name(s) in {len(groups)} worker(s), "
              f"XSECTIONS_TIME_FACTOR={factor:g}, XSECTIONS_REALDATA {realdata}", flush=True)
        ws = [Worker(i, g, run_dir / f"worker_{i}.log",
                     worker_env(factor, mpl_folder(run_dir, i, seed), f"{tag}w{i}_"))
              for i, g in enumerate(groups, 1)]
        everyone.extend(ws)
        run_all(ws, "worker")
        wall = time.perf_counter() - t_start

        # ---- the parallel results; a worker that did not end as unittest ends (no result, an exit status that
        # disagrees with the result it printed, or none at all: hung after its result; or timed out) counts as crashed
        totals = dict.fromkeys(COUNT_KEYS, 0)
        failing = []
        for w in ws:
            for k in COUNT_KEYS:
                totals[k] += w.result.counts.get(k, 0)
            failing.extend(dict(f, worker=w) for f in w.result.failing())
        crashed = [w for w in ws if w.timed_out or not w.result.exit_ok(w.returncode)]
        missing, explained = not_run(listing, ws, crashed) if listing is not None else ([], 0)
        expected = len(listing.all_ids()) - explained if listing is not None else None

        # ---- remember the times of the modules and classes asked for whole, and of each test of a second or more;
        # only after a run that is unittest's own (one process, or nothing split) or that ran every listed test
        per_module, per_class, per_test = measured_times(ws, modules)
        try:
            (run_dir / "times.json").write_text(json.dumps(
                {"wall": round(wall, 2), "listed": None if listing is None else len(listing.all_ids()),
                 "listing": None if listing is None else round(listing.seconds, 2), "workers": [
                     {"worker": w.label, "names": w.names, "wall": round(w.t1 - w.t0, 2), "exit": w.returncode,
                      "hung": w.hung, "timed_out": w.timed_out, "deadline": round(w.deadline, 1),
                      "exit_read": w.exit_read, "startup": round(w.result.startup, 2),
                      "tail": round(w.result.tail, 2),
                      "tests": [[t[0], t[1], round(t[3] - t[2], 3), round(t[4], 3)] for t in w.result.tests]}
                     for w in ws]}, indent=1), encoding="utf-8")
        except OSError:
            pass
        previous = data.get("last_full_run")
        verified = not crashed and (listing is None or (not missing and totals["run"] == expected))
        if verified:
            asked = [split_name(n, modules) for n in names]
            whole_modules = {m for m, c, _x in asked if m and not c}
            whole_classes = {f"{m}.{c}" for m, c, x in asked if m and c and not x}
            for mod, (t, n) in per_module.items():
                if mod in whole_modules:
                    remember(data, "modules", mod, t, n)
            for key, (t, n) in per_class.items():
                if key.rsplit(".", 1)[0] in whole_modules or key in whole_classes:
                    remember(data, "classes", key, t, n)
            for tid, t in per_test.items():
                if t >= 1.0 or tid in data["tests"]:
                    remember(data, "tests", tid, t, 1)
            if not args.names:
                data["last_full_run"] = {"tests": totals["run"], "wall": round(wall, 1), "workers": len(groups),
                                         "when": datetime.datetime.now().isoformat(timespec="seconds")}
            save_durations(data)

        # ---- when several processes ran: every failed one once more, in one process, factor 1 (a run in one
        # process is the serial run already: its result stands)
        rerun, rw = {}, None
        targets = list(dict.fromkeys(f["target"] for f in failing))
        if targets and not args.no_rerun and len(ws) > 1:
            print(f"Running the {len(targets)} that failed again, alone in one process (XSECTIONS_TIME_FACTOR=1) ...",
                  flush=True)
            # (its plan, for its deadline: make_units in one process keeps each target as one unit, names unchanged)
            rw = Worker("re-run", make_units(targets, modules, data, 1), run_dir / "rerun.log",
                        worker_env(1.0, mpl_folder(run_dir, "rerun", seed), tag + "rerun_"))
            everyone.append(rw)
            run_all([rw], "serial")
            rr = rw.result
            bad = [f["target"] for f in rr.failing()]
            ran_ids = [t[0] for t in rr.tests]
            for t in targets:
                ran_it = any(i == t or i.startswith(t + ".") for i in ran_ids)
                failed = any(b == t or b.startswith(t + ".") or t.startswith(b + ".") for b in bad)
                # (exit code 1 is unittest's own after a failure: one target failing again does not sink the others)
                passed = rr.exit_ok(rw.returncode) and not rw.timed_out and ran_it and not failed
                rerun[t] = "ok" if passed else "FAILED"
    except KeyboardInterrupt:
        held = held_temp(listers + everyone)
        removed = remove_run_temp(tag, keep=[w.tag for w, _p in held])
        print(f"\nINTERRUPTED: its processes were ended and {removed} temp folder(s) of theirs removed. "
              f"Logs: {run_dir}", flush=True)
        for line in held_lines(held):
            print(line, flush=True)
        return 1

    # ---- the temp folders of the run's processes, but those of a process that has not ended (hung, or stuck in
    # Windows' tear-down after its exit status was read; the listing process too): it may still hold them
    held = held_temp(listers + everyone)
    removed = remove_run_temp(tag, keep=[w.tag for w, _p in held])
    hung = [w for w in everyone if w.hung]          # (workers: a listing process that hung after its list is noted)
    timed_out = [w for w in everyone if w.timed_out]

    # ---- the report
    one = len(ws) == 1
    lines = []
    out = lines.append
    out("")
    out("Workers (wall time, tests, start-up = Python, QGIS and the imports before its first test, exit status)")
    for w in ws:
        r = w.result
        state = r.verdict if r.finished else "NO RESULT"
        if w.timed_out:
            state += ", TIMED OUT"
        elif w.hung:
            state += " BUT HUNG AFTER ITS RESULT"
        elif r.finished and not r.exit_ok(w.returncode):
            state += f" BUT EXIT CODE {exit_text(w.returncode)}"
        if w.exit_read:
            state += " (exit status read while its output was still open)"
        out(f"  {w.label}: {w.t1 - w.t0:7.1f} s  {r.counts['run']:4d} tests  start-up {r.startup:4.1f} s  "
            f"exit {'none' if w.hung or w.returncode is None else exit_text(w.returncode)}  {state}  "
            f"{w.log_path.name}")
        out("       " + " ".join(n[len("tests."):] if n.startswith("tests.") else n for n in w.names))
    out("Modules (seconds in their worker, slowest first)")
    for mod, (t, n) in sorted(per_module.items(), key=lambda kv: -kv[1][0]):
        where = sorted({w.label for w in ws for u in w.units if u.module == mod})
        out(f"  {t:7.1f} s  {n:4d} tests  {mod}" + (f"  (split: workers {', '.join(map(str, where))})"
                                                    if len(where) > 1 else ""))
    for w in crashed:
        out("")
        if w.timed_out:
            out(timed_out_text(w))
        elif w.hung:
            out(hung_text(w))
        elif w.result.finished:
            out(f"WORKER {w.label} ENDED WITH EXIT CODE {exit_text(w.returncode)} AFTER ITS RESULT "
                f"({w.result.verdict}; unittest ends with {w.result.expected_exit()} after that): the process ended "
                f"badly after its tests (a crash at exit?). See {w.log_path}")
        else:
            last = w.result.tests[-1][0] if w.result.tests else "(none had started)"
            out(f"WORKER {w.label} ENDED WITHOUT A RESULT (exit code {exit_text(w.returncode)}); the last test it "
                f"started: {last}. The rest of its names did not run. See {w.log_path}")
    if missing:
        out("")
        out(f"NOT RUN: {len(missing)} of the {len(listing.all_ids())} tests unittest's loader lists for these names "
            f"started in no worker (no set-up error or skip of their class or module explains it):")
        for tid in missing[:25]:
            out(f"  {tid}")
        if len(missing) > 25:
            out(f"  ... and {len(missing) - 25} more")
    ok, final, rescued = decide(totals, failing, rerun, len(crashed), modules)
    ok = ok and not missing
    if failing:
        out("")
        out("Failed:" if one else "Failed in parallel:")
        for f in failing:
            t = f["target"]
            again = rerun.get(t, "not run again")
            note = ""
            if t in rescued:
                note = " -> a timing test that passed alone: counted as passed"
            elif again == "ok":
                note = " -> passed alone, but it is not a timing test: still a failure"
            tagged = "@timing_test" if is_timing_test(t, modules) else ""
            if one:
                out(f"  {f['label']:<17} {t}" + (f"  ({tagged}; one process: not run again)" if tagged else ""))
            else:
                out(f"  {f['label']:<17} {t}  (worker {f['worker'].label}; alone: {again}"
                    f"{'; ' + tagged if tagged else ''}){note}")
        for f in failing:
            block = f["worker"].result.block_for(f["id"])
            if block:
                out(SEP1)
                out(block)
                out(f"(in {f['worker'].log_path})")
        if rw is not None:
            out(SEP1)
            out(f"Serial re-run: {worker_state(rw)}  ({rw.log_path})")
            for f in rw.result.failing():
                block = rw.result.block_for(f["id"])
                if block:
                    out(block)
    out("")
    if not args.names and previous and previous.get("tests") != totals["run"]:
        out(f"NOTE: the last full run ran {previous.get('tests')} tests ({previous.get('when', '')}); this one "
            f"{totals['run']}.")
    for w in listers:
        if w.note():
            out(f"NOTE: {w.note()}.")
    for w in everyone:
        if w.exit_read:
            how = "after unittest's result" if printed_result(w.text) else "and it had no result"
            out(f"NOTE: {late_exit_note(w)} (PID {getattr(w.proc, 'pid', '?')}: nothing came for "
                f"{w.result_grace:g} s {how}, its output still open).")
    for line in held_lines(held):
        out(line)
    if listing is not None and verified:
        n = len(listing.all_ids())
        out(f"Checked against unittest's loader: {'the 1 test' if n == 1 else f'all {n} tests'} it lists for these "
            f"names started." if not explained
            else f"Checked against unittest's loader: {n - explained} of the {n} tests it lists for these names "
                 f"started; the other {explained} were stopped by a set-up error or skip of their class or module.")
    if not verified:
        out("The times of this run are not remembered (a worker ended badly, hung or timed out, or not every listed "
            "test ran).")
    if rescued:
        out(f"{len(rescued)} timing test(s) failed under the parallel load and passed alone (listed above).")
    out(f"Wall time {wall:.1f} s, {len(groups)} worker(s), XSECTIONS_TIME_FACTOR={factor:g}; the workers' times add "
        f"up to {sum(w.t1 - w.t0 for w in ws):.1f} s; {removed} temp folder(s) of its processes removed"
        f"{f' ({sum(len(p) for _w, p in held)} left in place: above)' if held else ''}. Logs and summary.txt: "
        f"{run_dir}")
    out(SEP2)
    out(f"Ran {totals['run']} test{'' if totals['run'] == 1 else 's'} in {wall:.3f}s")
    out("")
    infos = []
    if not ok:
        infos += [f"{k}={final[k]}" for k in ("failures", "errors") if final[k] > 0]
        plain = [w for w in crashed if not (w.hung or w.timed_out)]
        if plain:
            infos.append(f"crashed workers={len(plain)}")
        if hung:
            infos.append(f"hung workers={len(hung)}")
        if timed_out:
            infos.append(f"timed out workers={len(timed_out)}")
        if missing:
            infos.append(f"not run={len(missing)}")
        if not infos:                                   # (failed in parallel, not counted by unittest)
            infos.append(f"failures={len({f['target'] for f in failing if f['target'] not in rescued})}")
    infos += [f"{k}={final[k]}" for k in ("skipped", "expected failures", "unexpected successes") if final[k]]
    # as unittest: NO TESTS RAN (exit 5) when no test ran and none was skipped
    no_tests = ok and NO_TESTS_EXIT is not None and totals["run"] == 0 and final["skipped"] == 0
    out(("NO TESTS RAN" if no_tests else "OK" if ok else "FAILED") + (f" ({', '.join(infos)})" if infos else ""))
    report = "\n".join(lines)
    print(report, flush=True)
    try:
        (run_dir / "summary.txt").write_text(report + "\n", encoding="utf-8", errors="backslashreplace")
    except OSError:
        pass
    return NO_TESTS_EXIT if no_tests else (0 if ok else 1)


if __name__ == "__main__":
    if sys.argv[1:2] == [LIST_FLAG]:
        sys.exit(list_main(sys.argv[2:]))
    sys.exit(main())
