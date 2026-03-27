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
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("spool: native C library build failed, falling back to pure Python", file=sys.stderr)


setup(cmdclass={"build_py": BuildWithNative})
