"""nmr_sim must not depend on the rest of PyNMR (so it can be removed or reused cleanly)."""

import ast
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = {"core", "gui", "hardware", "config", "utils", "PySide6", "pyqtgraph"}


def test_no_pynmr_imports_in_source():
    bad = []
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for n in names:
                if n.split(".")[0] in FORBIDDEN:
                    bad.append(f"{path.relative_to(PKG)}: {n}")
    assert not bad, bad


def test_adapter_import_pulls_in_nothing_from_pynmr():
    code = ("import sys, nmr_sim.adapter; "
            f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {sorted(FORBIDDEN)!r}); "
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], cwd=PKG.parent,
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
