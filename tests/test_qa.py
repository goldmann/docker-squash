from pathlib import Path
from subprocess import PIPE, run

import pytest


def test_formatting(monkeypatch):
    """Code formatting"""

    repo_root = str(Path(__file__).parent.parent)
    cmd = [repo_root + "/support/run_formatter.py", "--check"]
    monkeypatch.delenv("PYTHONPATH", raising=False)
    ret = run(cmd, stdout=PIPE, stderr=PIPE, encoding="utf-8", check=False)
    if ret.returncode:
        msg = [
            f"Command: {' '.join(cmd)}",
            f"Code: {ret.returncode}",
            f"STDOUT:\n{ret.stdout}",
            f"STDERR:\n{ret.stderr}" if ret.stderr else "",
        ]
        pytest.fail("\n".join(msg), pytrace=False)
