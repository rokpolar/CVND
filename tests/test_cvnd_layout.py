"""Tests for path resolution and console-output safety.

The encoding guard is not cosmetic. The Windows console defaults to a legacy
codepage (cp949 on the development machine), and printing an em dash or "km²"
there raises UnicodeEncodeError. That made `--help` exit with a traceback on every
script, and it killed a local run on the FIRST event, because the per-event status
line in sar_flood_area.py contains an em dash. Colab is UTF-8 and never saw it.
"""

import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cvnd_layout as cl  # noqa: E402

# Characters that actually appear in this project's output.
TRICKY = "— km² λ ✓ ✗ ≥ → –"


class PrintableOutputTests(unittest.TestCase):
    def test_non_ascii_survives_a_legacy_codepage(self):
        buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949", newline="")
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = buf
        try:
            with self.assertRaises(UnicodeEncodeError):
                buf.write(TRICKY)
                buf.flush()
            cl.ensure_printable_output()
            sys.stdout.write(TRICKY)       # must not raise now
            sys.stdout.flush()
        finally:
            sys.stdout, sys.stderr = real_out, real_err

    def test_a_stream_without_reconfigure_is_left_alone(self):
        """StringIO and captured pipes have no reconfigure(); the helper must not
        crash the program it exists to protect."""
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = io.StringIO()
        try:
            cl.ensure_printable_output()
            sys.stdout.write(TRICKY)
        finally:
            sys.stdout, sys.stderr = real_out, real_err

    def test_it_is_idempotent(self):
        cl.ensure_printable_output()
        cl.ensure_printable_output()

    def test_every_cli_calls_it_before_printing(self):
        """argparse prints help during parse_args(), so the call has to come
        first inside main() -- that is one of the two places this crashed."""
        entry_points = [p for p in sorted((ROOT / "src").glob("*.py"))
                        if "__main__" in p.read_text(encoding="utf-8")
                        and "def main(" in p.read_text(encoding="utf-8")]
        self.assertGreater(len(entry_points), 5)
        for p in entry_points:
            src = p.read_text(encoding="utf-8")
            self.assertIn("ensure_printable_output()", src, msg=p.name)
            i_main = src.index("def main(")
            i_call = src.index("ensure_printable_output()", i_main)
            # nothing but the signature/docstring between them
            between = src[i_main:i_call]
            self.assertLess(between.count("\n"), 12, msg=f"{p.name}: called late")


class DataPathTests(unittest.TestCase):
    def test_unknown_key_names_the_known_ones(self):
        with self.assertRaises(KeyError) as cm:
            cl.data_path("not-a-key")
        self.assertIn("sar_flood_area", str(cm.exception))

    def test_the_floodvit_output_is_registered(self):
        """merge_results.py reads this; without a registered key the FloodViT
        areas never reach the severity column."""
        self.assertTrue(str(cl.data_path("sar_flood_area")).endswith(".csv"))

    def test_paths_are_absolute(self):
        for key in ("events", "sar_flood_area", "severity_raw"):
            self.assertTrue(cl.data_path(key).is_absolute(), msg=key)


if __name__ == "__main__":
    unittest.main()
