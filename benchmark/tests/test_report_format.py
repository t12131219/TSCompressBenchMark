"""Pure display regressions; do not import or execute any codec or run."""
import ast
from pathlib import Path
import unittest


def formatting_functions():
    source = Path(__file__).resolve().parents[1] / "tools/report_all_core_results.py"
    parsed = ast.parse(source.read_text(), filename=str(source))
    functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"number", "rate"}]
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["number"], namespace["rate"]


number, rate = formatting_functions()


class ReportFormatTests(unittest.TestCase):
    def test_small_nonzero_metrics_remain_nonzero(self):
        for value, precision, expected in ((1.23e-5, 2, "1.23e-05"),
                                           (0.00999, 2, "9.99e-03"),
                                           (5e-7, 3, "5.000e-07"),
                                           (-5e-7, 3, "-5.000e-07")):
            with self.subTest(value=value, precision=precision):
                self.assertEqual(number(value, precision), expected)
                self.assertNotEqual(float(number(value, precision)), 0)

    def test_zero_missing_and_normal_values_keep_existing_display(self):
        self.assertEqual(number(None), "—")
        self.assertEqual(number(0, 2), "0.00")
        self.assertEqual(number(0.01, 2), "0.01")
        self.assertEqual(number(1.23456, 3), "1.235")
        self.assertEqual(number(100, 1), "100.0")

    def test_tiny_throughput_preserves_median_and_inverted_quartiles(self):
        row = {"complete_case": True, "raw_bytes": 1,
               "metrics": {"encode_ns": {"median": 1e9, "q1": .5e9, "q3": 2e9}}}
        self.assertEqual(rate(row, "encode"), "9.54e-07 [4.77e-07, 1.91e-06]")

    def test_normal_throughput_and_incomplete_case_keep_existing_display(self):
        row = {"complete_case": True, "raw_bytes": 2**20,
               "metrics": {"decode_ns": {"median": .5e9, "q1": .25e9, "q3": 1e9}}}
        self.assertEqual(rate(row, "decode"), "2.00 [1.00, 4.00]")
        self.assertEqual(rate({"complete_case": False}, "decode"), "—")


if __name__ == "__main__":
    unittest.main()
