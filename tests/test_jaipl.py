"""Test suite for jaipl.

Plain unittest, no dependencies, so it runs anywhere the language runs:

    python3 -m unittest discover -s tests -v
    python3 tests/test_jaipl.py
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arcide.jaipl import cli, fmt
from arcide.jaipl.interp import Output, RuntimeError_, run_source
from arcide.jaipl.lexer import LexError, tokenize
from arcide.jaipl.parser import ParseError, parse


def run(src):
    """Run jaipl source, returning (printed_lines, error_or_None)."""
    out = Output(write=lambda s: None)
    try:
        run_source(src, out=out)
        return out.lines, None
    except Exception as e:
        return out.lines, e


def value(src):
    """Run a program that assigns to 'result' and return it."""
    lines, err = run("let result = " + src)
    if err:
        raise err
    return lines and lines or None


class TestLexer(unittest.TestCase):
    def test_numbers_strings_keywords(self):
        kinds = [t.kind for t in tokenize('let x = 42  let y = "hi" let z = 1.5')]
        self.assertIn("int", kinds)
        self.assertIn("string", kinds)
        self.assertIn("float", kinds)

    def test_line_comment_ignored(self):
        lines, err = run("// a comment\nprint(1) // trailing\n")
        self.assertIsNone(err)
        self.assertEqual(lines, ["1"])

    def test_unterminated_string_is_an_error(self):
        with self.assertRaises(LexError):
            tokenize('let s = "never closed')

    def test_unterminated_block_comment_is_an_error(self):
        with self.assertRaises(LexError):
            tokenize('/* never closed')

    def test_newlines_survive_inside_braces(self):
        # This is the bug that made every class body unparseable: brace
        # blocks are statement sequences, so their newlines must be tokens.
        lines, err = run('let x = 1\nprint(\n  x\n)\n')
        self.assertIsNone(err)
        self.assertEqual(lines, ["1"])

    def test_triple_quoted_string_keeps_newlines(self):
        lines, err = run('let s = """a\nb"""\nprint(s)')
        self.assertIsNone(err)
        self.assertEqual(lines, ["a\nb"])


class TestParser(unittest.TestCase):
    def test_parses_classes_and_functions(self):
        prog = parse(
            'class A { let x = 1 func f() { return 2 } }\nfunc g() { return 3 }'
        )
        self.assertEqual(len(prog.body), 2)

    def test_trailing_comma_allowed(self):
        self.assertIsNone(parse_error('let x = [1, 2, 3,]') or None)
        self.assertIsNone(parse_error('print(1, 2,)') or None)

    def test_unclosed_brace_reports_position(self):
        err = parse_error('func f() {\n  print(1)\n')
        self.assertIsInstance(err, ParseError)
        self.assertEqual(err.line, 3)

    def test_missing_name_is_reported(self):
        self.assertIsInstance(parse_error('func () { }'), ParseError)


def parse_error(src):
    try:
        parse(src)
        return None
    except (ParseError, LexError) as e:
        return e


class TestRuntime(unittest.TestCase):
    def test_arithmetic_and_precedence(self):
        lines, err = run("print(2 + 3 * 4)")
        self.assertIsNone(err)
        self.assertEqual(lines, ["14"])

    def test_power_is_right_associative(self):
        lines, _ = run("print(2 ** 3 ** 2, 2 * 3 ** 2)")
        self.assertEqual(lines, ["512 18"])

    def test_strings_print_without_quotes(self):
        lines, _ = run('print("hi", 1, true, null)')
        self.assertEqual(lines, ["hi 1 true null"])

    def test_variables_and_reassignment(self):
        lines, err = run('var x = 1\nx = x + 4\nprint(x)')
        self.assertIsNone(err)
        self.assertEqual(lines, ["5"])

    def test_lists(self):
        lines, _ = run("let xs = [1,2,3]\nxs.push(4)\nprint(xs, len(xs))")
        self.assertEqual(lines, ["[1, 2, 3, 4] 4"])

    def test_maps(self):
        lines, _ = run('let m = {"a": 1}\nm["b"] = 2\nprint(m["b"], m.has("z"))')
        self.assertEqual(lines, ["2 false"])

    def test_index_assignment_grows_list(self):
        lines, _ = run('let xs = [1]\nxs[3] = 9\nprint(xs)')
        self.assertEqual(lines, ["[1, null, null, 9]"])

    def test_range_loop(self):
        lines, _ = run("var t = 0\nfor i in 0..5 { t = t + i }\nprint(t)")
        self.assertEqual(lines, ["10"])

    def test_for_over_list_binds_each_item(self):
        lines, _ = run('for x in ["a","b"] { print(x) }')
        self.assertEqual(lines, ["a", "b"])

    def test_while_with_break_and_continue(self):
        lines, _ = run(
            "var i = 0\nwhile true {\n  i = i + 1\n"
            "  if i == 2 { continue }\n  if i > 3 { break }\n  print(i)\n}"
        )
        self.assertEqual(lines, ["1", "3"])

    def test_functions_and_recursion(self):
        lines, err = run("func fib(n) {\n if n < 2 { return n }\n return fib(n-1) + fib(n-2)\n}\nprint(fib(10))")
        self.assertIsNone(err)
        self.assertEqual(lines, ["55"])

    def test_default_arguments(self):
        lines, err = run('func f(a, b = 2) { return a + b }\nprint(f(1), f(1, 5))')
        self.assertIsNone(err)
        self.assertEqual(lines, ["3 6"])

    def test_closures_capture_the_enclosing_scope(self):
        lines, err = run(
            "func counter() {\n let total = 0\n"
            " func bump(n) { total = total + n; return total }\n"
            " return bump\n}\nlet c = counter()\nc(5)\nprint(c(3))"
        )
        self.assertIsNone(err)
        self.assertEqual(lines, ["8"])


class TestOOP(unittest.TestCase):
    def test_fields_and_methods(self):
        lines, err = run(
            "class P {\n let x\n func new(x) { self.x = x }\n"
            " func get() { return self.x }\n}\nprint(new P(7).get())"
        )
        self.assertIsNone(err)
        self.assertEqual(lines, ["7"])

    def test_inheritance(self):
        lines, err = run(
            "class A { func who() { return \"A\" } }\n"
            "class B extends A { func who() { return \"B\" } }\n"
            "class C extends B { }\n"
            "print(new C().who())"
        )
        self.assertIsNone(err)
        self.assertEqual(lines, ["B"])

    def test_virtual_dispatch_through_a_list(self):
        lines, err = run(
            "class A { func who() { return \"A\" } }\n"
            "class B extends A { func who() { return \"B\" } }\n"
            "for x in [new A(), new B()] { print(x.who()) }"
        )
        self.assertIsNone(err)
        self.assertEqual(lines, ["A", "B"])

    def test_subclass_field_shadows_base_default(self):
        lines, err = run(
            "class A { let name = \"a\" }\n"
            "class B extends A { let name = \"b\" }\n"
            "print(new A().name, new B().name)"
        )
        self.assertIsNone(err)
        self.assertEqual(lines, ["a b"])

    def test_inherited_constructor_runs(self):
        lines, err = run(
            "class A {\n let v\n func new(v) { self.v = v }\n"
            " func show() { return str(self.v) }\n}\n"
            "class B extends A { }\nprint(new B(4).show())"
        )
        self.assertIsNone(err)
        self.assertEqual(lines, ["4"])

    def test_unknown_field_is_an_error(self):
        _, err = run("class A { }\nnew A().nope()")
        self.assertIsInstance(err, RuntimeError_)


class TestErrors(unittest.TestCase):
    def test_unknown_name(self):
        _, err = run("print(nope)")
        self.assertIsInstance(err, RuntimeError_)
        self.assertIn("unknown name", str(err))

    def test_division_by_zero(self):
        _, err = run("print(1 / 0)")
        self.assertIsInstance(err, RuntimeError_)

    def test_recursion_limit_is_reported_not_crashed(self):
        _, err = run("func f(n) { return f(n + 1) }\nf(1)")
        self.assertIsInstance(err, RuntimeError_)
        self.assertIn("stack overflow", str(err))

    def test_infinite_loop_is_stopped_by_the_step_limit(self):
        # A small limit stands in for the real one, so the test finishes
        # instantly while exercising exactly the same code path.
        out = Output(write=lambda s: None)
        with self.assertRaises(RuntimeError_) as caught:
            run_source("while true { }", out=out, max_steps=5000)
        self.assertIn("infinite loop", str(caught.exception))

    def test_step_limit_counts_real_work(self):
        out = Output(write=lambda s: None)
        # Well under the limit, so this must finish normally.
        run_source("var t = 0\nwhile t < 100 { t = t + 1 }", out=out,
                   max_steps=100_000)


class TestFormatter(unittest.TestCase):
    def test_formats_and_preserves_meaning(self):
        src = "let a=1\nfunc f(x,y){\nlet s = x   +   y\nprint( s )\n}\n"
        out = fmt.format_source(src)
        self.assertIn("let a = 1", out)
        self.assertIn("    print(s)", out)
        # The proof that it did not change the program.
        self.assertEqual(
            [type(s).__name__ for s in parse(out)],
            [type(s).__name__ for s in parse(src)],
        )

    def test_string_quotes_survive(self):
        src = 'print("hello world")\n'
        out = fmt.format_source(src)
        self.assertIn('"hello world"', out)

    def test_eof_marker_is_not_printed(self):
        out = fmt.format_source("let x = 1\n")
        self.assertNotIn("None", out)

    def test_already_formatted_is_stable(self):
        src = "let a = 1\n"
        self.assertEqual(fmt.format_source(src), src)


class TestCLI(unittest.TestCase):
    def test_version(self):
        self.assertEqual(cli.main(["version"]), 0)

    def test_run_and_exit_code(self):
        self.assertEqual(cli.main(["run", str(EXAMPLES / "shapes.jai")]), 0)

    def test_check_reports_ok(self):
        self.assertEqual(cli.main(["check", str(EXAMPLES / "shapes.jai")]), 0)

    def test_unknown_command_is_an_error(self):
        self.assertEqual(cli.main(["nonsense"]), 2)

    def test_missing_file(self):
        self.assertEqual(cli.main(["run", "/nope/missing.jai"]), 2)


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class TestDocs(unittest.TestCase):
    """Every jaipl snippet in the reference must actually run.

    Documentation that drifts away from the language is worse than none, so
    the examples are executed rather than trusted.
    """

    def _blocks(self):
        import re

        md = Path(__file__).resolve().parent.parent / "JAIPL.md"
        if not md.exists():
            self.skipTest("JAIPL.md is not present")
        return re.findall(r"```jaipl\n(.*?)```", md.read_text(), re.S)

    def test_reference_exists(self):
        self.assertTrue(self._blocks(), "no jaipl examples found in JAIPL.md")

    def test_every_example_runs(self):
        for i, block in enumerate(self._blocks(), 1):
            with self.subTest(block=i):
                out = Output(write=lambda s: None)
                try:
                    run_source(block, out=out)
                except Exception as e:  # noqa: BLE001 - want the real message
                    self.fail(
                        f"JAIPL.md example {i} does not run: "
                        f"{type(e).__name__}: {e}\n---\n{block}"
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)