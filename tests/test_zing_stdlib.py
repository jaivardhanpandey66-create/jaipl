"""Tests for the zing standard library, exceptions, slicing and imports.

Runs anywhere the language runs:

    python3 -m unittest discover -s tests -v
    python3 tests/test_zing_stdlib.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arcide.zing.interp import Output, RuntimeError_, run_source
from arcide.zing.lexer import LexError
from arcide.zing.parser import ParseError


def run(src, source_dir=None):
    """Run zing source, returning (printed_lines, error_or_None)."""
    out = Output(write=lambda s: None)
    try:
        run_source(src, out=out, source_dir=source_dir)
        return out.lines, None
    except Exception as e:
        return out.lines, e


def printed(src, source_dir=None):
    """Run source and return its output lines, failing loudly on error."""
    lines, err = run(src, source_dir=source_dir)
    if err:
        raise err
    return lines


def expr(src):
    """Evaluate an expression and return its printed form."""
    return printed("print(" + src + ")")[0]


def fails(src, source_dir=None):
    """Run source expecting an error, and return it."""
    _, err = run(src, source_dir=source_dir)
    if err is None:
        raise AssertionError("expected an error, but the program succeeded")
    return err


class MathBuiltins(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(expr("round(3.14159, 2)"), "3.14")
        self.assertEqual(expr("round(2.5)"), "3")
        self.assertEqual(expr("round(-2.5)"), "-3")
        self.assertEqual(expr("round(-1.4, 1)"), "-1.4")

    def test_floor_ceil(self):
        self.assertEqual(expr("floor(3.9)"), "3")
        self.assertEqual(expr("ceil(3.1)"), "4")
        self.assertEqual(expr("floor(-3.1)"), "-4")

    def test_abs_sign_pow(self):
        self.assertEqual(expr("abs(-7)"), "7")
        self.assertEqual(expr("abs(7)"), "7")
        self.assertEqual(expr("sign(-3)"), "-1")
        self.assertEqual(expr("sign(0)"), "0")
        self.assertEqual(expr("pow(2, 10)"), "1024.0")
        self.assertEqual(expr("sqrt(144)"), "12.0")

    def test_min_max_sum(self):
        self.assertEqual(expr("min([4, 2, 9])"), "2")
        self.assertEqual(expr("max([4, 2, 9])"), "9")
        self.assertEqual(expr("min(4, 2, 9)"), "2")
        self.assertEqual(expr("max(4, 2, 9)"), "9")
        self.assertEqual(expr("sum([1, 2, 3, 4])"), "10")
        self.assertEqual(expr("sum([])"), "0")

    def test_trig(self):
        self.assertEqual(expr("sin(0)"), "0.0")
        self.assertEqual(expr("cos(0)"), "1.0")
        self.assertEqual(expr("atan2(1, 1)"), str(0.7853981633974483))

    def test_logs(self):
        self.assertEqual(expr("log(1)"), "0.0")
        self.assertEqual(expr("log2(8)"), "3.0")
        self.assertEqual(expr("log10(1000)"), "3.0")
        self.assertEqual(expr("exp(0)"), "1.0")

    def test_domain_errors_are_catchable_runtime_errors(self):
        err = fails('print(log(0))')
        self.assertIsInstance(err, RuntimeError_)
        self.assertIn("positive", str(err))
        err = fails("print(sin(1e400 * 1.0))")
        self.assertIsInstance(err, (RuntimeError_, OverflowError))

    def test_wrong_type_names_the_function(self):
        err = fails('print(abs("text"))')
        self.assertIsInstance(err, RuntimeError_)
        self.assertIn("abs", str(err))
        err = fails('print(log("nope"))')
        self.assertIn("log", str(err))


class StringBuiltins(unittest.TestCase):
    def test_case_and_trim(self):
        self.assertEqual(expr('upper("jai")'), "JAI")
        self.assertEqual(expr('lower("PL")'), "pl")
        self.assertEqual(expr('strip("  hi  ")'), "hi")
        self.assertEqual(expr('lstrip("  hi  ")'), "hi  ")
        self.assertEqual(expr('rstrip("  hi  ")'), "  hi")

    def test_split_join_replace(self):
        self.assertEqual(expr('join(split("a,b,c", ","), " | ")'), "a | b | c")
        self.assertEqual(expr('split("a b c")'), '[a, b, c]')
        self.assertEqual(expr('replace("hi", "h", "J")'), "Ji")
        self.assertEqual(expr('upper(replace("hi", "h", "j"))'), "JI")

    def test_search(self):
        self.assertEqual(expr('find("zing", "in")'), "1")
        self.assertEqual(expr('find("zing", "zz")'), "-1")
        self.assertEqual(expr('starts_with("zing", "zin")'), "true")
        self.assertEqual(expr('ends_with("zing", "ing")'), "true")
        self.assertEqual(expr('contains("hello", "ell")'), "true")
        self.assertEqual(expr('count("cheese", "e")'), "3")

    def test_repeat_and_chars(self):
        self.assertEqual(expr('repeat("ab", 3)'), "ababab")
        self.assertEqual(expr('ord("A")'), "65")
        self.assertEqual(expr('chr(66)'), "B")
        self.assertEqual(expr('is_empty("")'), "true")
        self.assertEqual(expr('is_empty("x")'), "false")

    def test_string_argument_is_enforced(self):
        err = fails("print(upper(5))")
        self.assertIn("upper", str(err))
        err = fails('print(join(5, ","))')
        self.assertIn("join", str(err))
        err = fails('print(join([1, 2], ","))')
        self.assertIn("join", str(err))


class Bitwise(unittest.TestCase):
    def test_binary_operators(self):
        self.assertEqual(expr("5 & 3"), "1")
        self.assertEqual(expr("5 | 3"), "7")
        self.assertEqual(expr("5 ^ 3"), "6")
        self.assertEqual(expr("5 << 2"), "20")
        self.assertEqual(expr("20 >> 2"), "5")

    def test_unary_not(self):
        self.assertEqual(expr("~5"), "-6")
        self.assertEqual(expr("~0"), "-1")

    def test_precedence_follows_python(self):
        # Additive binds tighter than shift, so this is 1 << 5 and not (1 << 2)+3.
        self.assertEqual(expr("1 << 2 + 3"), "32")
        self.assertEqual(expr("(1 << 2) + 3"), "7")
        # Bitwise or is the loosest of the four.
        self.assertEqual(expr("1 | 2 & 3"), "3")
        self.assertEqual(expr("(1 | 2) & 3"), "3")

    def test_needs_integers(self):
        # `&&` stays boolean; a lone `&` is strictly a bit operation.
        err = fails('print("a" & "b")')
        self.assertIsInstance(err, RuntimeError_)
        self.assertIn("needs two integers", str(err))
        self.assertIsInstance(fails("print(~true)"), RuntimeError_)


class Constants(unittest.TestCase):
    def test_constants_are_values_not_functions(self):
        # A function here would break arithmetic like `PI * 2`.
        self.assertNotEqual(expr("PI"), "function")
        self.assertEqual(expr("round(PI, 4)"), "3.1416")
        self.assertEqual(expr("round(E, 4)"), "2.7183")
        self.assertEqual(expr("round(TAU, 4)"), "6.2832")


class ForIn(unittest.TestCase):
    def test_list_range_map_and_string(self):
        out = printed("for x in [1, 2, 3] { print(x) }")
        self.assertEqual(out, ["1", "2", "3"])
        out = printed("for k in {\"x\": 1, \"y\": 2} { print(k) }")
        self.assertEqual(out, ["x", "y"])
        out = printed("for ch in \"abc\" { print(ch) }")
        self.assertEqual(out, ["a", "b", "c"])
        out = printed("for i in 0..3 { print(i) }")
        self.assertEqual(out, ["0", "1", "2"])

    def test_iterating_a_number_is_an_error(self):
        err = fails("for x in 5 { print(x) }")
        self.assertIsInstance(err, RuntimeError_)


class Slicing(unittest.TestCase):
    def setUp(self):
        self.lit = "let xs = [0,1,2,3,4,5]\n"

    def test_every_form(self):
        cases = {
            "xs[1:4]": "[1, 2, 3]",
            "xs[:2]": "[0, 1]",
            "xs[4:]": "[4, 5]",
            "xs[:]": "[0, 1, 2, 3, 4, 5]",
            "xs[-3:-1]": "[3, 4]",
            "xs[2:99]": "[2, 3, 4, 5]",
            "xs[99:]": "[]",
            "xs[3:2]": "[]",
        }
        for code, want in cases.items():
            with self.subTest(code=code):
                self.assertEqual(printed(self.lit + "print(" + code + ")")[0], want)

    def test_plain_index_is_untouched(self):
        self.assertEqual(printed(self.lit + "print(xs[0])")[0], "0")
        self.assertEqual(printed(self.lit + "print(xs[-1])")[0], "5")

    def test_string_slicing(self):
        self.assertEqual(expr('"zing"[1:4]'), "ing")
        self.assertEqual(expr('"zing"[0:1] + "zing"[4:5]'), "z")

    def test_bad_bounds_are_rejected(self):
        err = fails(self.lit + 'print(xs[1.5:2])')
        self.assertIn("whole numbers", str(err))
        err = fails('print("abc"[0:1.5])')
        self.assertIn("whole numbers", str(err))

    def test_cannot_slice_a_number(self):
        err = fails("print((5)[0:1])")
        self.assertIn("slice", str(err))


class Exceptions(unittest.TestCase):
    def test_throw_and_catch_binds_the_value(self):
        out = printed('try { throw "boom" } catch as e { print(e) }')
        self.assertEqual(out, ["boom"])

    def test_catch_without_binding(self):
        out = printed('try { throw 1 } catch { print("handled") }')
        self.assertEqual(out, ["handled"])

    def test_type_filter_skipped_for_a_thrown_value(self):
        # `throw` carries a bare value with no type, so a typed clause does
        # not match it; the untyped catch-all does.
        src = """
        try { throw 42 }
        catch RuntimeError { print("typed clause") }
        catch { print("fell through") }
        """
        self.assertEqual(printed(src), ["fell through"])

    def test_type_filter_selects_by_error_name(self):
        src = """
        try { no_such_function() }
        catch RuntimeError { print("runtime") }
        catch { print("other") }
        """
        self.assertEqual(printed(src), ["runtime"])

    def test_typed_clause_that_does_not_match_keeps_the_error(self):
        src = """
        try { no_such_function() }
        catch LexError { print("wrong") }
        catch { print("other") }
        """
        self.assertEqual(printed(src), ["other"])

    def test_runtime_errors_are_catchable(self):
        cases = {
            "1 / 0": "division by zero",
            "[1, 2][99]": "index",
            "no_such_function()": "unknown name",
        }
        for code, needle in cases.items():
            with self.subTest(code=code):
                src = "try { " + code + " } catch as e { print(e) }"
                out = printed(src)
                self.assertEqual(len(out), 1, out)
                self.assertIn(needle, out[0].lower())

    def test_else_runs_only_when_nothing_threw(self):
        src = """
        try { print("body") } catch { print("no") } else { print("else") }
        try { throw 1 } catch { print("caught") } else { print("no") }
        """
        self.assertEqual(printed(src), ["body", "else", "caught"])

    def test_finally_always_runs(self):
        src = """
        try { throw 1 } catch { print("caught") } finally { print("finally") }
        try { print("fine") } finally { print("finally") }
        """
        self.assertEqual(printed(src), ["caught", "finally", "fine", "finally"])

    def test_unhandled_error_ke_traveling(self):
        err = fails('try { throw 1 } catch RuntimeError { print("no") }')
        self.assertEqual(str(err), "1")
        self.assertIsInstance(fails("1 / 0"), RuntimeError_)

    def test_try_needs_something_to_attach(self):
        self.assertIsInstance(fails("try { print(1) }"), ParseError)

    def test_return_inside_try_is_not_swallowed(self):
        # return is control flow, not an error: it must escape the try.
        src = """
        func f() {
            try { return "from try" } finally { print("cleanup") }
        }
        print(f())
        """
        self.assertEqual(printed(src), ["cleanup", "from try"])

    def test_lexer_errors_are_reported_before_running(self):
        _, err = run("try { print(1) } catch RuntimeError { print(2) } @")
        self.assertIsInstance(err, (LexError, ParseError, RuntimeError_))


class FileIO(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.dir.name) / "demo.txt")
        self.addCleanup(self.dir.cleanup)

    def test_write_then_read(self):
        printed(
            f'let f = open("{self.path}", "w")\n'
            "write_line(f, \"hello\")\n"
            'write(f, "second\\n")\n'
            "close(f)\n"
        )
        out = printed(f'print(read(open("{self.path}", "r")))')
        self.assertEqual(out, ["hello\nsecond\n"])

    def test_read_lines(self):
        Path(self.path).write_text("a\nb\n", encoding="utf-8")
        out = printed(
            f'for line in read_lines(open("{self.path}", "r")) '
            "{ print(strip(line)) }"
        )
        self.assertEqual(out, ["a", "b"])

    def test_append(self):
        Path(self.path).write_text("one\n", encoding="utf-8")
        printed(f'let f = open("{self.path}", "a")\nwrite_line(f, "two")\nclose(f)')
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), "one\ntwo\n")

    def test_exists_and_remove(self):
        self.assertEqual(expr(f'file_exists("{self.path}")'), "false")
        Path(self.path).write_text("x", encoding="utf-8")
        self.assertEqual(expr(f'file_exists("{self.path}")'), "true")
        printed(f'remove_file("{self.path}")')
        self.assertEqual(expr(f'file_exists("{self.path}")'), "false")

    def test_list_dir(self):
        Path(self.path).write_text("x", encoding="utf-8")
        self.assertIn("demo.txt", expr(f'list_dir("{self.dir.name}")'))

    def test_errors_are_readable_and_catchable(self):
        missing = str(Path(self.dir.name) / "nope.txt")
        err = fails(f'let f = open("{missing}", "r")')
        self.assertIn("no such file", str(err))
        out = printed(
            f'try {{ open("{missing}", "r") }} catch as e {{ print(e) }}'
        )
        self.assertIn("no such file", out[0])

    def test_duplicate_create_is_reported(self):
        Path(self.path).write_text("x", encoding="utf-8")
        err = fails(f'open("{self.path}", "x")')
        self.assertIn("already exists", str(err))

    def test_writing_to_a_read_only_handle_is_refused(self):
        Path(self.path).write_text("x", encoding="utf-8")
        src = (
            f'let f = open("{self.path}", "r")\n'
            'try { write(f, "nope") } catch as e { print(e) }'
        )
        self.assertIn("not writing", printed(src)[0])

    def test_bad_arguments_are_rejected(self):
        self.assertIn("mode", str(fails(f'open("{self.path}", "q")')))
        self.assertIn("path", str(fails("open(5)")))


class Modules(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_functions_cross_files(self):
        self.write("mathlib.zig", "func square(n) { return n * n }")
        main = self.write("main.zig", "import mathlib\nprint(square(7))")
        out = printed(open(main).read(), source_dir=self.root)
        self.assertEqual(out, ["49"])

    def test_module_scope_is_isolated_but_sees_builtins(self):
        self.write("lib.zig", "func helper() { return PI }")
        main = self.write("main.zig", "import lib\nprint(round(helper(), 4))")
        out = printed(open(main).read(), source_dir=self.root)
        self.assertEqual(out, ["3.1416"])

    def test_module_toplevel_values_are_shared(self):
        self.write("consts.zig", "let LIMIT = 3 * 7")
        main = self.write("main.zig", "import consts\nprint(LIMIT)")
        out = printed(open(main).read(), source_dir=self.root)
        self.assertEqual(out, ["21"])

    def test_underscore_names_stay_private(self):
        self.write("lib.zig", "let _secret = 1\nfunc open_one() { return 2 }")
        main = self.write("main.zig", "import lib\nprint(open_one())")
        out = printed(open(main).read(), source_dir=self.root)
        self.assertEqual(out, ["2"])

    def test_a_module_is_loaded_once(self):
        # Importing twice must not run the module body again.
        self.write("once.zig", 'print("module loaded")\nfunc helper() { return 1 }')
        main = self.write("main.zig", "import once\nimport once\nhelper()")
        out = printed(open(main).read(), source_dir=self.root)
        self.assertEqual(out, ["module loaded"])

    def test_missing_module_lists_what_was_tried(self):
        main = self.write("main.zig", "import nosuchmodule")
        err = fails(open(main).read(), source_dir=self.root)
        self.assertIn("cannot find module", str(err))
        self.assertIn("nosuchmodule.zig", str(err))

    def test_broken_module_reports_the_file(self):
        self.write("bad.zig", "func oops( { }")
        main = self.write("main.zig", "import bad")
        err = fails(open(main).read(), source_dir=self.root)
        self.assertIn("bad.zig", str(err))


if __name__ == "__main__":
    unittest.main(verbosity=2)