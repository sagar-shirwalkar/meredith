from __future__ import annotations

from coding_agent.context.compressor import OutputCompressor

compressor = OutputCompressor()


class TestCommandCompression:
    def test_compress_test_output_simple(self):
        """Test output gets summary + failures."""
        output = """\
============================= test session starts ==============================
tests/test_stuff.py .F
=========================== short test summary info ============================
FAILED tests/test_stuff.py::test_bar - AssertionError: assert False
1 failed, 1 passed in 0.3s
"""
        result = compressor.compress("run_command", output)
        assert "PASSED" in result or "passed" in result

    def test_compress_build_output_general(self):
        output = "\n".join(f"line {i}" for i in range(100))
        result = compressor.compress("run_command", output)
        lines = result.split("\n")
        assert len(lines) < 100

    def test_compress_short_output(self):
        output = "Hello world"
        result = compressor.compress("run_command", output)
        assert result == "Hello world"


class TestTestSummaryExtraction:
    def test_extract_test_summary(self):
        output = """\
collected 3 items
tests/test_foo.py::test_ok PASSED
tests/test_foo.py::test_fail FAILED
tests/test_foo.py::test_skip SKIPPED

========== 1 failed, 1 passed, 1 skipped in 0.1s ==========
"""
        result = compressor._extract_test_summary(output)
        assert "1 failed, 1 passed, 1 skipped" in result

    def test_extract_test_summary_with_failures_section(self):
        output = """\
tests/test_foo.py .F
FAILED tests/test_foo.py::test_bar
1 failed, 1 passed in 0.1s
"""
        result = compressor._extract_test_summary(output)
        assert "1 failed, 1 passed" in result

    def test_extract_test_summary_fallback(self):
        output = "\n".join(f"line {i}" for i in range(50))
        result = compressor._extract_test_summary(output)
        # Fallback returns last 20 lines
        assert len(result.split("\n")) <= 20

    def test_looks_like_test_output(self):
        assert compressor._looks_like_test_output("3 passed, 1 failed in 0.3s") is True
        assert compressor._looks_like_test_output("pytest output") is True
        assert compressor._looks_like_test_output("just some text") is False

    def test_looks_like_error_output(self):
        assert compressor._looks_like_error_output("error: foo\nwarning: bar\nerror: baz") is True
        assert compressor._looks_like_error_output("just text") is False


class TestSearchCompression:
    def test_compress_search_keeps_within_limit(self):
        output = "\n".join(f"match {i}: something" for i in range(50))
        result = compressor.compress("search_code", output, {"budget_remaining": 0.5})
        lines = result.split("\n")
        assert len(lines) <= 31  # 30 lines + 1 omitted indicator

    def test_compress_search_low_budget(self):
        output = "\n".join(f"match {i}: something" for i in range(50))
        result = compressor.compress("search_code", output, {"budget_remaining": 0.1})
        lines = result.split("\n")
        assert len(lines) <= 16  # 15 lines + 1 omitted indicator
        assert "more matches omitted" in result

    def test_compress_search_truncates_long_lines(self):
        output = "\n".join(f"match {i}: " + "x" * 300 for i in range(5))
        result = compressor.compress("search_code", output, {"budget_remaining": 0.5})
        for line in result.split("\n"):
            if line and not line.startswith("..."):
                assert len(line) <= 200 + 5  # max_line_length + " ..."


class TestFileCompression:
    def test_compress_file_high_budget(self):
        output = "def foo():\n    pass\n"
        result = compressor.compress("read_file", output, {"budget_remaining": 0.8})
        assert result == output

    def test_compress_file_strips_docstrings(self):
        output = '''"""Module docstring."""

def foo():
    """Function docstring."""
    pass
'''
        result = compressor.compress("read_file", output, {"budget_remaining": 0.4})
        assert "Module docstring" not in result
        assert "Function docstring" not in result
        assert "def foo()" in result

    def test_compress_file_keeps_todos(self):
        output = "# TODO: fix this\ndef foo():  # FIXME: slow\n    pass\n"
        result = compressor.compress("read_file", output, {"budget_remaining": 0.4})
        assert "TODO" in result
        assert "FIXME" in result


class TestHardLimit:
    def test_hard_char_limit_enforced(self):
        very_long = "x" * 5000
        result = compressor.compress("run_command", very_long)
        assert len(result) <= 4000

    def test_compress_directory(self):
        output = "file1.py\nfile2.py\nsubdir/\n"
        result = compressor.compress("list_directory", output)
        assert "file1.py" in result

    def test_compress_directory_low_budget(self):
        output = "top.txt\n  indented.txt\nanother.txt\n"
        result = compressor.compress("list_directory", output, {"budget_remaining": 0.1})
        assert "indented.txt" not in result

    def test_compress_unknown_tool(self):
        output = "some output"
        result = compressor.compress("unknown_tool", output)
        assert result == "some output"

    def test_compress_references(self):
        output = "\n".join(f"ref {i}: somewhere" for i in range(50))
        result = compressor.compress("find_references", output)
        lines = result.split("\n")
        assert len(lines) <= 21  # 15 + 5 + 1 omitted

    def test_truncate_middle(self):
        text = "hello world foo bar baz qux"
        result = OutputCompressor._truncate_middle(text, 10)
        assert "[heavily truncated]" in result
