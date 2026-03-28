import os
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithNative(build_py):
    def run(self):
        super().run()
        src = Path(__file__).parent / "spool" / "reader" / "logindex.c"
        out_dir = Path(self.build_lib) / "spool" / "reader"
        out_dir.mkdir(parents=True, exist_ok=True)
        so = out_dir / "liblogindex.so"
        try:
            subprocess.check_call(["gcc", "-O3", "-shared", "-fPIC", "-Wall", "-o", str(so), str(src)])
            print("spool: native C library built successfully", file=sys.stderr)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            print("  spool: NATIVE C LIBRARY BUILD FAILED", file=sys.stderr)
            print("", file=sys.stderr)
            print("  gcc not found or compilation failed.", file=sys.stderr)
            print("  Search will use the pure Python fallback.", file=sys.stderr)
            print("  This is ~10x slower on large log files.", file=sys.stderr)
            print("", file=sys.stderr)
            print("  Install gcc and reinstall spool to fix:", file=sys.stderr)
            print("    apt install gcc  (or equivalent)", file=sys.stderr)
            print("    pip install --force-reinstall spool", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            print("", file=sys.stderr)


setup(cmdclass={"build_py": BuildWithNative})
