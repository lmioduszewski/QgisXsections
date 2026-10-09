"""scripts/run_tests_parallel.py, the parallel test launcher: its reading of a unittest -v stream (made here by
unittest itself, so the format is this Python's), a worker's exit status, what it runs again, the @timing_test tags it
finds in the tree, the listing of the tests by unittest's loader and how it splits and balances along it, the check
that every listed test ran, Ctrl+C, the golden refusal, the per-worker matplotlib folder; and fixtures'
XSECTIONS_TIME_FACTOR. Nothing here starts a process or QGIS (main() runs with its processes replaced)."""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures
from tests.fixtures import ROOT


def load_launcher():
    spec = importlib.util.spec_from_file_location("xsec_run_tests_parallel",
                                                  os.path.join(ROOT, "scripts", "run_tests_parallel.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_launcher()
MOD = "tests.test_fake"


def verbose_stream():
    """A -v run of made-up tests (classes made here, so the suite never collects them) as one worker's output would
    be: what the tests print interleaved with unittest's lines. Classes and ids are renamed to tests.test_fake."""

    class A(unittest.TestCase):
        def test_a_ok(self):
            pass

        def test_b_docstring_and_print(self):
            """A docstring's first line goes on its own line."""
            print("\n  printed by the test")

        def test_c_fails(self):
            self.assertEqual(1, 2)

        def test_d_errors(self):
            raise RuntimeError("boom")

        @unittest.skip("no data here")
        def test_e_skipped(self):
            pass

        def test_f_subtests(self):
            for i in range(3):
                with self.subTest(i=i):
                    self.assertNotEqual(i % 2, 0)

        @unittest.expectedFailure
        def test_g_expected(self):
            self.assertTrue(False)

    class B(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            raise OSError("no setup")

        def test_never_runs(self):
            pass

    class C(unittest.TestCase):
        @classmethod
        def tearDownClass(cls):
            raise ValueError("bad teardown")

        def test_only(self):
            pass

    for cls in (A, B, C):
        cls.__module__ = MOD
        cls.__qualname__ = cls.__name__
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(c) for c in (A, B, C)])
    suite.addTest(loader.loadTestsFromName("tests.test_no_such_module_xyz"))      # an import that fails
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        unittest.TextTestRunner(stream=out, verbosity=2).run(suite)
    return out.getvalue()


def stream_of(results, *extra_classes):
    """The -v stream unittest itself writes for made-up tests {id: "ok" | "FAIL" | "ERROR"} (a class per
    module.Class, its tests in unittest's order), then for `extra_classes` (TestCase classes made by the caller)."""
    def body(outcome):
        def test(self):
            if outcome == "FAIL":
                self.fail("made to fail")
            if outcome == "ERROR":
                raise RuntimeError("made to fail")
        return test
    classes = {}
    for tid, outcome in results.items():
        mod, cls, method = tid.rsplit(".", 2)
        if f"{mod}.{cls}" not in classes:
            c = type(cls, (unittest.TestCase,), {})
            c.__module__, c.__qualname__ = mod, cls
            classes[f"{mod}.{cls}"] = c
        setattr(classes[f"{mod}.{cls}"], method, body(outcome))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(c) for c in [*classes.values(), *extra_classes]])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        unittest.TextTestRunner(stream=out, verbosity=2).run(suite)
    return out.getvalue()


def arrived(w, text):
    """`text` as a worker's output that arrived line by line, one second apart."""
    w.text = text
    pos, t = 0, 0.0
    for line in text.splitlines(keepends=True):
        pos += len(line)
        t += 1.0
        w.ends.append(pos)
        w.times.append(t)
    w.t0, w.t1 = 0.0, t + 1.0
    return w


def fake_worker(text, names=(MOD,)):
    """A Worker that never ran: its text arrived line by line, one second apart."""
    return arrived(P.Worker("1", [P.Unit(n) for n in names], os.devnull, {}), text)


def ast_listing(modules, made=None):
    """A Listing as the listing process gives it for `modules`, made here from the source (ast), plus the tests a class
    makes at import time: made = {"module.Class": [test names]}."""
    made = made or {}
    ids, parts = {}, {}
    for m in modules:
        info = P.module_info(m)
        ids[m], classes = [], []
        for c in info.test_classes():
            mine = [f"{m}.{c}.{t}" for t in sorted(info.tests_of(c) + made.get(f"{m}.{c}", []))]
            ids[m] += mine
            classes.append([f"{m}.{c}", len(mine)])
            parts[f"{m}.{c}"] = [[t, 1] for t in mine]
        if classes:
            parts[m] = classes
    return P.Listing({"ids": ids, "parts": parts})


class ReadingTheStream(unittest.TestCase):
    def check(self, text):
        r = P.Result(fake_worker(text, names=(MOD, "tests.test_no_such_module_xyz")))
        self.assertTrue(r.finished)
        status = {tid.rsplit(".", 1)[-1]: s for tid, s, *_x in r.tests}
        self.assertEqual(status, {"test_a_ok": "ok", "test_b_docstring_and_print": "ok", "test_c_fails": "FAIL",
                                  "test_d_errors": "ERROR", "test_e_skipped": "skipped", "test_f_subtests": "FAIL",
                                  "test_g_expected": "expected", "test_only": "ok", "test_no_such_module_xyz": "ERROR"})
        self.assertEqual(r.counts["run"], 9)
        # unittest's own counts: two subtests failed, the set-up and tear-down errors count as errors
        self.assertEqual((r.counts["failures"], r.counts["errors"], r.counts["skipped"], r.counts["expected failures"]),
                         (3, 4, 1, 1))
        self.assertTrue(r.verdict.startswith("FAILED ("))
        sub = next(t for t in r.tests if t[0].endswith("test_f_subtests"))
        self.assertEqual((sub[5], sub[6]), (2, 0))
        fails = {(f["target"], f["label"]) for f in r.failing()}
        self.assertEqual(fails, {(f"{MOD}.A.test_c_fails", "FAIL"), (f"{MOD}.A.test_d_errors", "ERROR"),
                                 (f"{MOD}.A.test_f_subtests", "FAIL"), (f"{MOD}.B", "setUpClass ERROR"),
                                 (f"{MOD}.C", "tearDownClass ERROR"),
                                 ("tests.test_no_such_module_xyz", "import ERROR")})
        # the test before the tear-down error keeps its own status ("ok"), and its traceback is found
        self.assertIn("AssertionError: 1 != 2", r.block_for(f"{MOD}.A.test_c_fails"))
        self.assertIn("RuntimeError: boom", r.block_for(f"{MOD}.A.test_d_errors"))
        self.assertIn("OSError: no setup", r.block_for(f"{MOD}.B"))
        self.assertNotIn("RuntimeError", r.block_for(f"{MOD}.A.test_c_fails"))
        return r

    def test_a_stream_as_unittest_writes_it(self):
        text = verbose_stream()
        r = self.check(text)
        # line by line, one second apart: test_b started on its line and ended at its "ok" after the printed lines
        b = next(t for t in r.tests if t[0].endswith("test_b_docstring_and_print"))
        self.assertGreaterEqual(b[3] - b[2], 2.0)

    def test_windows_line_ends(self):
        self.check(verbose_stream().replace("\n", "\r\n"))

    def test_a_worker_that_crashed(self):
        text = verbose_stream()
        cut = text.index("test_d_errors (")
        r = P.Result(fake_worker(text[:cut] + "test_d_errors (tests.test_fake.A.test_d_errors) ... "))
        self.assertFalse(r.finished)
        self.assertEqual(r.tests[-1][:2], [f"{MOD}.A.test_d_errors", "crashed"])
        self.assertIn(f"{MOD}.A.test_d_errors", {f["target"] for f in r.failing()})
        self.assertEqual(r.verdict, "no result")
        self.assertFalse(r.exit_ok(0))

    def test_a_class_skipped_in_its_set_up(self):
        class S(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("no data here")

            def test_never_runs(self):
                pass
        S.__module__, S.__qualname__ = MOD, "S"
        r = P.Result(fake_worker(stream_of({f"{MOD}.A.test_a": "ok"}, S)))
        self.assertEqual([t[:2] for t in r.tests], [[f"{MOD}.A.test_a", "ok"]])        # (the skip is not its status)
        self.assertEqual(r.fixture_skips, [("setUpClass", f"{MOD}.S")])
        self.assertEqual(r.fixture_errors, [])
        self.assertTrue(r.explains(f"{MOD}.S.test_never_runs"))
        self.assertFalse(r.explains(f"{MOD}.A.test_b"))
        self.assertEqual((r.verdict, r.failing()), ("OK (skipped=1)", []))


class ExitStatus(unittest.TestCase):
    """A worker has passed only when it ended as `python -m unittest` ends after the result it printed."""

    def test_it_must_agree_with_the_result(self):
        ok = P.Result(fake_worker(stream_of({f"{MOD}.A.test_a": "ok"})))
        self.assertTrue(ok.exit_ok(0))
        for rc in (1, 3, 5, 0xC0000005, -11, None):          # printed OK, then crashed (in QGIS's shutdown, say)
            self.assertFalse(ok.exit_ok(rc), rc)
        failed = P.Result(fake_worker(verbose_stream(), names=(MOD, "tests.test_no_such_module_xyz")))
        self.assertEqual([failed.exit_ok(rc) for rc in (1, 0, 3, 0xC0000005)], [True, False, False, False])
        self.assertEqual(P.exit_text(0xC0000005), "3221225477 = 0xC0000005")
        self.assertEqual(P.exit_text(1), "1")

    @unittest.skipIf(P.NO_TESTS_EXIT is None, "unittest exits 5 for no tests from Python 3.12")
    def test_no_test_ran(self):
        none = P.Result(fake_worker(stream_of({})))
        self.assertEqual(none.verdict, "NO TESTS RAN")
        self.assertEqual([none.exit_ok(rc) for rc in (5, 0, 1)], [True, False, False])

        # a class whose set-up failed, and nothing else: FAILED, and unittest still ends with 5 (no test ran)
        class B(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise OSError("no setup")

            def test_never_runs(self):
                pass
        B.__module__, B.__qualname__ = MOD, "B"
        r = P.Result(fake_worker(stream_of({}, B)))
        self.assertTrue(r.verdict.startswith("FAILED"))
        self.assertEqual([r.exit_ok(rc) for rc in (5, 1, 0)], [True, False, False])


class TimingTags(unittest.TestCase):
    def test_tags_in_the_tree(self):
        modules = P.discover_modules()
        self.assertIn("tests.test_parallel_runner", modules)
        yes = ["tests.test_point_layers.Speed.test_find_explorations_budget",          # the class is tagged
               "tests.test_point_layers.Speed",
               "tests.test_preview_tools.SpeedTest.test_a_hover_update_is_quick",       # the method is tagged
               "tests.test_realdata_gpkg.RealGeoPackagePanel.test_budgets"]
        no = ["tests.test_preview_tools.SpeedTest.test_a_hover_repaints_only_what_it_changes",
              "tests.test_preview_tools.ZoomTest.test_zoom_limit_is_a_pixel_budget",     # "budget", not a timing test
              "tests.test_preview_tools",
              "tests.test_scales.Sheets.test_letter_landscape"]
        self.assertEqual([t for t in yes if not P.is_timing_test(t, modules)], [])
        self.assertEqual([t for t in no if P.is_timing_test(t, modules)], [])

    def test_ast_sees_bases_and_tags(self):
        src = ("import unittest\nfrom tests.fixtures import timing_test\n"
               "class Base(unittest.TestCase):\n    @timing_test\n    def test_x(self): pass\n"
               "    def test_y(self): pass\n"
               "@timing_test\nclass Tagged(Base):\n    def test_z(self): pass\n"
               "class Child(Base):\n    pass\n"
               "class Mixin:\n    def test_m(self): pass\n")
        folder = Path(tempfile.mkdtemp(prefix="xsec_ast_"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "mod.py").write_text(src, encoding="utf-8")
        with mock.patch.object(P, "ROOT", folder):
            info = P.ModuleInfo("mod")
        self.assertEqual(info.test_classes(), {"Base": 2, "Child": 2, "Tagged": 3})
        self.assertEqual(info.tests_of("Child"), ["test_x", "test_y"])
        self.assertTrue(info.is_timing("Child", "test_x"))
        self.assertFalse(info.is_timing("Child", "test_y"))
        self.assertTrue(info.is_timing("Tagged", "test_z"))
        self.assertTrue(info.is_timing("Tagged", "test_y"))


class Planning(unittest.TestCase):
    def data(self):
        modules = P.discover_modules()
        data = {"modules": {m: {"time": 1.0, "tests": sum(P.module_info(m).test_classes().values())}
                            for m in modules}, "classes": {}, "tests": {}}
        data["modules"]["tests.test_layout"] = {"time": 260.0, "tests": 30}
        for c, n in P.module_info("tests.test_layout").test_classes().items():
            data["classes"][f"tests.test_layout.{c}"] = {"time": 1.0, "tests": n}
        data["classes"]["tests.test_layout.EveryCombination"] = {"time": 229.0, "tests": 3}
        data["tests"]["tests.test_layout.EveryCombination.test_tiled_tabloid"] = {"time": 120.0, "tests": 1}
        data["modules"]["tests.test_compat_032"] = {"time": 150.0, "tests": 18}
        data["classes"]["tests.test_compat_032.Compat032"] = {"time": 150.0, "tests": 18}
        return modules, data

    MADE = {"tests.test_compat_032.Compat032": [f"test_case{k}_{i}" for k in range(5) for i in range(3)]}

    def test_a_long_module_is_split_down_to_its_tests(self):
        modules, data = self.data()
        listing = ast_listing(modules, self.MADE)
        units = P.make_units(modules, modules, data, 6, listing)
        names = {u.name for u in units}
        self.assertNotIn("tests.test_layout", names)
        self.assertIn("tests.test_layout.Margins", names)
        self.assertIn("tests.test_layout.EveryCombination.test_tiled_tabloid", names)
        tiled = next(u for u in units if u.name.endswith("test_tiled_tabloid"))
        self.assertEqual(tiled.estimate, 120.0)
        others = [u.estimate for u in units if u.cls == "EveryCombination" and u.method != "test_tiled_tabloid"]
        self.assertEqual(others, [54.5, 54.5])                      # the rest of the class's time, shared
        # a class with tests made at import time (18 loaded, 3 in the source) is split along what the loader lists
        compat = [u.name for u in units if u.module == "tests.test_compat_032"]
        self.assertEqual(sorted(compat), listing.ids["tests.test_compat_032"])
        self.assertEqual(len(compat), 18)
        # every listed test is in exactly one unit
        for tid in listing.all_ids():
            self.assertEqual(len([u for u in units if tid == u.name or tid.startswith(u.name + ".")]), 1, tid)

    def test_nothing_is_split_without_the_listing_or_against_it(self):
        modules, data = self.data()
        self.assertEqual([u.name for u in P.make_units(modules, modules, data, 6)], modules)
        # (the review's case: only test_layout remembered, the generated tests' module long by its guess)
        partial = {"modules": {"tests.test_layout": {"time": 354.0, "tests": 30}}, "classes": {}, "tests": {}}
        names = ["tests.test_compat_032", "tests.test_scales.Sheets.test_named_sheet"]
        self.assertEqual([u.name for u in P.make_units(names, modules, partial, 6)], names)
        # a module the loader could not split exactly (say a class imported from elsewhere) stays whole
        listing = ast_listing(modules, self.MADE)
        del listing.parts["tests.test_compat_032"]
        self.assertEqual([u.name for u in P.make_units(names, modules, partial, 6, listing)], names)
        # and with the listing's parts, all 18 are there
        units = P.make_units(names, modules, partial, 6, ast_listing(modules, self.MADE))
        self.assertEqual(len([u for u in units if u.module == "tests.test_compat_032"]), 18)

    def test_balanced_longest_first(self):
        units = [P.Unit(f"tests.test_{k}", estimate=t) for k, t in enumerate([100, 60, 50, 40, 30, 20, 10])]
        groups = P.assign(units, 3)
        loads = sorted(sum(u.estimate for u in g) for g in groups)
        self.assertEqual(loads, [100, 100, 110])
        for g in groups:
            self.assertEqual([u.name for u in g], sorted(u.name for u in g))
        self.assertEqual(len(P.assign(units[:2], 6)), 2)            # never more workers than names

    def test_one_name_or_serial_is_one_process(self):
        modules, data = self.data()
        self.assertEqual([u.name for u in P.make_units(["tests.test_layout"], modules, data, 1)],
                         ["tests.test_layout"])
        units = P.make_units(["tests.test_scales", "tests.test_units"], modules, data, 6)
        self.assertEqual([u.name for u in units], ["tests.test_scales", "tests.test_units"])    # short: not split


class ListingTheTests(unittest.TestCase):
    """list_names (what the listing process runs), here in this process on a package of its own in a temp folder."""

    def test_parts_only_where_the_loader_agrees(self):
        folder = Path(tempfile.mkdtemp(prefix="xsec_list_"))
        self.addCleanup(shutil.rmtree, folder, True)
        pkg = f"xsec_list_pkg_{os.getpid()}"
        (folder / pkg).mkdir()
        files = {
            "__init__.py": "",
            "shared.py": "import unittest\n\n\nclass Shared(unittest.TestCase):\n    def test_s(self):\n        pass\n",
            "test_plain.py": ("import unittest\n\n\nclass A(unittest.TestCase):\n    def test_1(self):\n"
                              "        pass\n\n    def test_2(self):\n        pass\n\n\nclass B(unittest.TestCase):\n"
                              "    def test_1(self):\n        pass\n\n\nfor i in range(2):\n"
                              "    setattr(B, f'test_made_{i}', lambda self: None)\n"),
            "test_imported.py": (f"import unittest\nfrom {pkg}.shared import Shared  # noqa: F401\n\n\n"
                                 "class C(unittest.TestCase):\n    def test_c(self):\n        pass\n")}
        for name, text in files.items():
            (folder / pkg / name).write_text(text, encoding="utf-8")
        plain, imported = f"{pkg}.test_plain", f"{pkg}.test_imported"
        try:
            with mock.patch.object(sys, "path", [str(folder), *sys.path]), \
                    mock.patch.object(sys, "dont_write_bytecode", True), \
                    contextlib.redirect_stdout(io.StringIO()):
                found = P.list_names([plain, imported, f"{plain}.B", f"{pkg}.nope", plain])
        finally:
            for k in [k for k in sys.modules if k == pkg or k.startswith(pkg + ".")]:
                del sys.modules[k]
        made = [f"{plain}.B.test_1", f"{plain}.B.test_made_0", f"{plain}.B.test_made_1"]
        self.assertEqual(list(found["ids"]), [plain, imported, f"{plain}.B", f"{pkg}.nope"])
        self.assertEqual(found["ids"][plain], [f"{plain}.A.test_1", f"{plain}.A.test_2", *made])
        self.assertEqual(found["parts"][plain], [[f"{plain}.A", 2], [f"{plain}.B", 3]])
        # tests made at import time are the loader's: the class splits into all of them
        self.assertEqual(found["parts"][f"{plain}.B"], [[t, 1] for t in made])
        self.assertEqual(found["ids"][f"{plain}.B"], made)
        # a class imported from another module (its ids read <pkg>.shared.Shared...): the module stays whole
        self.assertIn(f"{pkg}.shared.Shared.test_s", found["ids"][imported])
        self.assertNotIn(imported, found["parts"])
        # a module that cannot be imported: one failed test, no parts
        self.assertEqual(found["ids"][f"{pkg}.nope"], ["unittest.loader._FailedTest.nope"])
        self.assertNotIn(f"{pkg}.nope", found["parts"])
        listing = P.Listing(found)
        self.assertEqual(listing.count(plain), 5)
        self.assertEqual(len(listing.all_ids()), 5 + 2 + 3 + 1)


class Launcher(unittest.TestCase):
    """main() itself, with its processes replaced: each worker's -v stream (made by unittest here) and exit status
    come from `outcome`; the run folders and durations.json go to a temp folder of this test."""
    A, B = "tests.test_fake_a", "tests.test_fake_b"
    TIMING = "tests.test_point_layers.Speed.test_find_explorations_budget"
    OTHER = "tests.test_scales.Sheets.test_letter_landscape"

    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix="xsec_launcher_"))
        self.addCleanup(shutil.rmtree, self.state, True)
        for name, value in (("STATE", self.state), ("DURATIONS", self.state / "durations.json"),
                            ("matplotlib_seed", lambda: None)):
            patcher = mock.patch.object(P, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(P, "remove_run_temp", return_value=0)
        self.remove = patcher.start()
        self.addCleanup(patcher.stop)
        self.runs = []

    def main(self, argv, outcome, listing=None):
        """(exit status, printed text, the list_tests mock); outcome(names, what) -> (stream, exit status)."""
        def run_all(ws, what):
            self.runs.append((what, [w.names for w in ws]))
            for w in ws:
                text, rc = outcome(w.names, what)
                arrived(w, text)
                w.returncode = rc
                w.result = P.Result(w)
        with mock.patch.object(P, "run_all", run_all), \
                mock.patch.object(P, "list_tests", return_value=listing) as listed, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            rc = P.main(argv)
        return rc, out.getvalue(), listed

    def listing(self, ids):
        return P.Listing({"ids": ids, "parts": {}})

    def two(self, a, b, listing=None):
        """Two workers, one module each: a(names) and b(names) give their (stream, exit status)."""
        return self.main(["--workers", "2", self.A, self.B], lambda names, what: (a if names == [self.A] else b),
                         listing or self.listing({self.A: [f"{self.A}.A.test_1"], self.B: [f"{self.B}.B.test_1"]}))

    def ok(self, name, cls):
        return stream_of({f"{name}.{cls}.test_1": "ok"}), 0

    def test_a_worker_that_prints_ok_then_crashes_fails_the_run(self):
        for rc in (0xC0000005, 3, 1):
            rc_run, text, _l = self.two((self.ok(self.A, "A")[0], rc), self.ok(self.B, "B"))
            self.assertEqual(rc_run, 1, rc)
            self.assertIn(f"ENDED WITH EXIT CODE {P.exit_text(rc)} AFTER ITS RESULT", text)
            self.assertTrue(text.rstrip().endswith("FAILED (errors=1, crashed workers=1)"), text[-300:])
            self.assertFalse(P.DURATIONS.exists())                  # (nothing remembered from such a run)
        rc_run, text, _l = self.two(self.ok(self.A, "A"), self.ok(self.B, "B"))
        self.assertEqual(rc_run, 0)
        self.assertTrue(text.rstrip().endswith("OK"))
        self.assertIn("exit 0  OK", text)
        self.assertTrue(P.DURATIONS.exists())

    @unittest.skipIf(P.NO_TESTS_EXIT is None, "unittest exits 5 for no tests from Python 3.12")
    def test_no_tests_ran(self):
        empty = (stream_of({}), 5)
        rc, text, _l = self.two(empty, self.ok(self.B, "B"), self.listing({self.A: [], self.B: [f"{self.B}.B.test_1"]}))
        self.assertEqual(rc, 0)                                     # (one worker with no tests is no failure)
        self.assertTrue(text.rstrip().endswith("OK"))
        rc, text, _l = self.two(empty, empty, self.listing({self.A: [], self.B: []}))
        self.assertEqual(rc, 5)                                     # (as unittest: nothing ran at all)
        self.assertTrue(text.rstrip().endswith("NO TESTS RAN"))

    def test_a_listed_test_that_never_started_fails_the_run(self):
        listing = self.listing({self.A: [f"{self.A}.A.test_1", f"{self.A}.A.test_2"], self.B: [f"{self.B}.B.test_1"]})
        rc, text, _l = self.two(self.ok(self.A, "A"), self.ok(self.B, "B"), listing)
        self.assertEqual(rc, 1)
        self.assertIn("NOT RUN: 1 of the 3 tests", text)
        self.assertIn(f"  {self.A}.A.test_2\n", text)
        self.assertTrue(text.rstrip().endswith("FAILED (not run=1)"), text[-200:])
        self.assertFalse(P.DURATIONS.exists())
        # a class skipped in its set-up explains its tests
        class S(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("no data here")

            def test_1(self):
                pass
        S.__module__, S.__qualname__ = self.A, "S"
        listing = self.listing({self.A: [f"{self.A}.A.test_1", f"{self.A}.S.test_1"], self.B: [f"{self.B}.B.test_1"]})
        rc, text, _l = self.two((stream_of({f"{self.A}.A.test_1": "ok"}, S), 0), self.ok(self.B, "B"), listing)
        self.assertEqual(rc, 0, text[-500:])
        self.assertIn("2 of the 3 tests it lists for these names started; the other 1 were stopped by a set-up", text)
        self.assertTrue(text.rstrip().endswith("OK (skipped=1)"))

    def test_one_process_never_runs_a_failure_again(self):
        def outcome(names, what):
            return stream_of({t: ("FAIL" if t == self.TIMING and what == "worker" else "ok") for t in names}), \
                int(what == "worker" and self.TIMING in names)
        for argv in (["--serial", self.TIMING, self.OTHER], ["--workers", "1", self.TIMING, self.OTHER],
                     [self.TIMING]):
            self.runs = []
            rc, text, listed = self.main(argv, outcome)
            self.assertEqual(rc, 1, argv)                           # as scripts\run_tests.bat
            self.assertEqual([what for what, _n in self.runs], ["worker"], argv)
            listed.assert_not_called()                              # (one process: unittest's own run)
            self.assertIn("\nFailed:\n", text)
            self.assertNotIn("passed alone", text)
            self.assertTrue(text.rstrip().endswith("FAILED (failures=1)"), text[-200:])
        # in parallel the tagged timing test that passes alone counts as passed
        self.runs = []
        rc, text, _l = self.main(["--workers", "2", self.TIMING, self.OTHER], outcome,
                                 self.listing({self.TIMING: [self.TIMING], self.OTHER: [self.OTHER]}))
        self.assertEqual(rc, 0, text[-800:])
        self.assertEqual([what for what, _n in self.runs], ["worker", "serial"])
        self.assertIn("a timing test that passed alone: counted as passed", text)

    def test_ctrl_c_ends_the_workers_and_removes_their_temp_folders(self):
        procs = []

        def start(w):
            w.proc = mock.MagicMock()
            w.proc.poll.return_value = None
            procs.append(w.proc)
        try:
            with mock.patch.object(P.Worker, "start", start), \
                    mock.patch.object(P.Worker, "done", side_effect=KeyboardInterrupt), \
                    mock.patch.object(P, "list_tests", return_value=None), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                rc = P.main(["--workers", "2", self.A, self.B])
        except KeyboardInterrupt:
            self.fail("Ctrl+C reached the caller")
        self.assertEqual(rc, 1)
        self.assertEqual(len(procs), 2)
        for proc in procs:
            proc.kill.assert_called_once_with()
            proc.wait.assert_called()
        self.remove.assert_called_once()
        self.assertTrue(self.remove.call_args[0][0].startswith("run_"))
        self.assertIn("INTERRUPTED", out.getvalue())


class Verdict(unittest.TestCase):
    TIMING = "tests.test_point_layers.Speed.test_find_explorations_budget"
    OTHER = "tests.test_scales.Sheets.test_letter_landscape"

    def decide(self, failing, rerun, crashed=0):
        totals = dict.fromkeys(P.COUNT_KEYS, 0)
        totals.update(run=100, skipped=2)
        for f in failing:
            totals["failures"] += f["nf"]
            totals["errors"] += f["ne"]
        return P.decide(totals, failing, rerun, crashed, P.discover_modules())

    def fail(self, target, label="FAIL"):
        return dict(target=target, id=target, label=label, nf=label == "FAIL", ne=label != "FAIL")

    def test_a_timing_test_that_passes_alone_counts_as_passed(self):
        ok, final, rescued = self.decide([self.fail(self.TIMING)], {self.TIMING: "ok"})
        self.assertTrue(ok)
        self.assertEqual((final["failures"], final["errors"], final["skipped"]), (0, 0, 2))
        self.assertEqual(rescued, {self.TIMING})
        # a timing class whose set-up failed, fine alone
        cls = "tests.test_point_layers.Speed"
        self.assertTrue(self.decide([self.fail(cls, "setUpClass ERROR")], {cls: "ok"})[0])

    def test_any_other_failure_stands(self):
        for failing, rerun in (([self.fail(self.OTHER)], {self.OTHER: "ok"}),            # not a timing test
                               ([self.fail(self.TIMING)], {self.TIMING: "FAILED"}),      # failed alone too
                               ([self.fail(self.TIMING)], {}),                           # not run again
                               ([self.fail(self.TIMING, "crashed")], {self.TIMING: "ok"}),
                               ([self.fail("tests.test_point_layers.Speed", "tearDownClass ERROR")],
                                {"tests.test_point_layers.Speed": "ok"}),
                               ([self.fail(self.TIMING), self.fail(self.OTHER)],
                                {self.TIMING: "ok", self.OTHER: "ok"})):
            ok, final, _r = self.decide(failing, rerun)
            self.assertFalse(ok, failing)
            self.assertGreater(final["failures"] + final["errors"], 0, failing)
        ok, final, _r = self.decide([], {}, crashed=1)
        self.assertFalse(ok)
        self.assertEqual(final["errors"], 1)
        self.assertTrue(self.decide([], {})[0])


class Refusals(unittest.TestCase):
    def test_golden_files_are_never_made_in_parallel(self):
        for var in P.GOLDEN_VARS:
            with mock.patch.dict(os.environ, {var: "1"}), mock.patch.object(P.subprocess, "Popen") as popen, \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(P.main(["--workers", "2", "tests.test_scales", "tests.test_units"]), 2)
            popen.assert_not_called()
            self.assertIn("Refused", out.getvalue())


class WorkerEnvironment(unittest.TestCase):
    def test_environment(self):
        with mock.patch.dict(os.environ, {"XSECTIONS_REALDATA": "R", "XSECTIONS_GPKG": "G",
                                          "XSECTIONS_TIME_FACTOR": "7"}):
            os.environ.pop("MPLCONFIGDIR", None)                    # (a parallel worker has its own)
            env = P.worker_env(3.0, Path("M"), "run_x_")
            one = P.worker_env(1.0, None)
        self.assertEqual((env["QT_QPA_PLATFORM"], env["PYTHONDONTWRITEBYTECODE"], env["PYTHONUNBUFFERED"]),
                         ("offscreen", "1", "1"))
        self.assertEqual((env["XSECTIONS_REALDATA"], env["XSECTIONS_GPKG"], env["XSECTIONS_TIME_FACTOR"],
                          env["MPLCONFIGDIR"], env["XSECTIONS_RUN_TAG"]), ("R", "G", "3", "M", "run_x_"))
        self.assertNotIn("XSECTIONS_TIME_FACTOR", one)              # one process: limits as written
        self.assertNotIn("MPLCONFIGDIR", one)
        self.assertNotIn("XSECTIONS_RUN_TAG", one)

    def test_run_temp_folders_removed_by_tag(self):
        # this process's RUN_TMP carries the tag it was given; the launcher removes its processes' folders by it
        self.assertTrue(os.path.basename(fixtures.RUN_TMP).startswith(
            "xsec_run_" + os.environ.get("XSECTIONS_RUN_TAG", "")))
        tmp = tempfile.gettempdir()                                 # (RUN_TMP itself here: nothing else is touched)
        mine = [tempfile.mkdtemp(prefix="xsec_run_run_test_tag_", dir=tmp) for _ in range(2)]
        Path(mine[0], "symbology-style.db").write_bytes(b"x")
        other = tempfile.mkdtemp(prefix="xsec_run_run_other_", dir=tmp)
        self.addCleanup(shutil.rmtree, other, True)
        self.assertEqual(P.remove_run_temp("run_test_tag_"), 2)
        self.assertEqual([os.path.isdir(p) for p in mine + [other]], [False, False, True])
        self.assertEqual(P.remove_run_temp(""), 0)

    def test_own_matplotlib_folder(self):
        tmp = Path(tempfile.mkdtemp(prefix="xsec_mpl_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src, run = tmp / "user", tmp / "run"
        (src / "stylelib").mkdir(parents=True)
        run.mkdir()
        for name in ("fontlist-v390.json", "matplotlibrc", "other.txt"):
            (src / name).write_text("x", encoding="utf-8")
        (src / "stylelib" / "mine.mplstyle").write_text("x", encoding="utf-8")
        dest = P.mpl_folder(run, 3, [src, src])
        self.assertEqual(dest, run / "mpl_3")
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["fontlist-v390.json", "matplotlibrc", "stylelib"])
        self.assertIsNone(P.mpl_folder(run, 4, None))


class TimeFactor(unittest.TestCase):
    def test_from_the_environment(self):
        for text, want in (("", 1.0), ("3", 3.0), (" 2.5 ", 2.5)):
            with mock.patch.dict(os.environ, {"XSECTIONS_TIME_FACTOR": text}):
                self.assertEqual(fixtures._time_factor(), want)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XSECTIONS_TIME_FACTOR", None)
            self.assertEqual(fixtures._time_factor(), 1.0)
        for bad in ("three", "0", "-1", "nan"):
            with mock.patch.dict(os.environ, {"XSECTIONS_TIME_FACTOR": bad}):
                with self.assertRaises(ValueError):
                    fixtures._time_factor()

    def test_limits_and_waits(self):
        with mock.patch.object(fixtures, "TIME_FACTOR", 3.0):
            self.assertEqual((fixtures.budget(1.5), fixtures.wait_ms(700), fixtures.wait_ms(20)), (4.5, 2100, 60))
        with mock.patch.object(fixtures, "TIME_FACTOR", 1.0):
            self.assertEqual((fixtures.budget(1.5), fixtures.wait_ms(700)), (1.5, 700))

    def test_tag_changes_nothing(self):
        def f():
            return 42
        self.assertIs(fixtures.timing_test(f), f)
        self.assertEqual(f(), 42)


if __name__ == "__main__":
    unittest.main()
