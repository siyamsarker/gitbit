"""Tests for the python -m gitbit entrypoint (__main__.py)."""
from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent


class TestModuleEntryPoint:
    def test_main_block_runs_in_process(self):
        """runpy executes __main__.py in-process with __name__='__main__', hitting the guard."""
        with patch("gitbit.cli.main") as mock_main:
            runpy.run_module("gitbit", run_name="__main__")
        mock_main.assert_called_once()

    def test_python_m_gitbit_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "gitbit", "--help"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0
        assert "gitbit" in result.stdout

    def test_python_m_gitbit_shows_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "gitbit", "--version"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0
        # version string appears somewhere (stdout or stderr)
        assert "0.3" in result.stdout or "0.3" in result.stderr
