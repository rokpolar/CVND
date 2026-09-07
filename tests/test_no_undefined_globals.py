"""Catch names a function reads globally that do not exist.

Motivation: refactoring the tiling loop into a generator renamed its parameter
from `done_blocks` to `skip`, but one line inside kept using the old name. Python
only raises on that line, so the mistake survived the test suite and a git push
and only surfaced after Earth Engine auth, a model load and a download had all
succeeded in Colab. Nothing here needs credentials, so it fails in a second.

Works by walking the compiled bytecode for LOAD_GLOBAL and checking each name
against the module's globals plus builtins -- precise, unlike scanning source
text, because attribute reads and locals are not LOAD_GLOBAL.
"""

import builtins
import dis
import importlib
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Modules that import without Earth Engine credentials or torch.
MODULES = [
    "cvnd_config",
    "cvnd_layout",
    "floodvit_infer",
    "merge_results",
    "sar_flood_area",
    "sar_patches",
]


def _code_objects(code):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _code_objects(const)


def undefined_globals(module):
    """Global names read by the module's functions that resolve nowhere."""
    known = set(vars(module)) | set(dir(builtins))
    missing = {}
    for name, obj in vars(module).items():
        code = getattr(obj, "__code__", None)
        if code is None or getattr(obj, "__module__", None) != module.__name__:
            continue
        for co in _code_objects(code):
            for ins in dis.get_instructions(co):
                if ins.opname == "LOAD_GLOBAL":
                    ref = ins.argval
                    if ref not in known:
                        missing.setdefault(ref, set()).add(name)
    return missing


class UndefinedGlobalTests(unittest.TestCase):
    def test_no_undefined_globals(self):
        for name in MODULES:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                missing = undefined_globals(mod)
                self.assertEqual(
                    missing, {},
                    f"{name}: undefined names " +
                    ", ".join(f"{n} (in {sorted(fs)})" for n, fs in missing.items()),
                )

    def test_the_check_actually_detects_one(self):
        """Guard the guard: a deliberately broken function must be reported."""
        mod = types.ModuleType("fake")
        mod.__name__ = "fake"
        src = "def f():\n    return not_defined_anywhere\n"
        exec(compile(src, "<fake>", "exec"), vars(mod))
        vars(mod)["f"].__module__ = "fake"
        self.assertIn("not_defined_anywhere", undefined_globals(mod))


if __name__ == "__main__":
    unittest.main()
