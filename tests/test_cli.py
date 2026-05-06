"""CLI integration tests using click.testing.CliRunner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from git_mirror.cli import main
from git_mirror.sync import RepoResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_file(tmp_path: Path, repos: list[dict] | None = None) -> str:
    cfg = {
        "global": {"parallel": 2, "timeout": 60, "mirrors_dir": str(tmp_path / "mirrors")},
        "repos": repos
        or [
            {
                "name": "RepoA",
                "source": "git@github.com:org/RepoA.git",
                "dest": "git@backup.example.com:mirrors/RepoA.git",
                "lfs": False,
                "submodules": False,
            }
        ],
    }
    p = tmp_path / "repos.json"
    p.write_text(json.dumps(cfg))
    return str(p)


def _ok(name: str = "RepoA") -> RepoResult:
    return RepoResult(name=name, success=True, message="ok")


def _fail(name: str = "RepoA") -> RepoResult:
    return RepoResult(name=name, success=False, message="clone failed")


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


class TestMainGroup:
    def test_version_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "git-mirror" in result.output

    def test_no_args_shows_usage(self):
        runner = CliRunner()
        result = runner.invoke(main, [])
        # Click exits 0 or 2 depending on version; either way usage must appear
        assert "Usage" in result.output


# ---------------------------------------------------------------------------
# sync-all
# ---------------------------------------------------------------------------


class TestSyncAll:
    def test_success_exits_zero(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            result = runner.invoke(main, ["sync-all", "-c", config])
        assert result.exit_code == 0
        mock_rp.assert_called_once()
        _, kwargs = mock_rp.call_args
        assert kwargs["dry_run"] is False

    def test_all_failures_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_fail()]), patch(
            "git_mirror.cli.print_summary"
        ):
            result = runner.invoke(main, ["sync-all", "-c", config])
        assert result.exit_code == 1

    def test_partial_failure_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch(
            "git_mirror.cli.run_parallel", return_value=[_ok("R1"), _fail("R2")]
        ), patch("git_mirror.cli.print_summary"):
            result = runner.invoke(main, ["sync-all", "-c", config])
        assert result.exit_code == 1

    def test_invalid_config_exits_one(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["sync-all", "-c", str(tmp_path / "missing.json")])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_dry_run_flag_propagated(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config, "--dry-run"])
        _, kwargs = mock_rp.call_args
        assert kwargs["dry_run"] is True

    def test_parallel_override(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config, "--parallel", "8"])
        _, kwargs = mock_rp.call_args
        assert kwargs["workers"] == 8

    def test_timeout_override(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config, "--timeout", "999"])
        _, kwargs = mock_rp.call_args
        assert kwargs["timeout"] == 999

    def test_config_defaults_used_when_no_overrides(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config])
        _, kwargs = mock_rp.call_args
        assert kwargs["workers"] == 2   # from config global.parallel
        assert kwargs["timeout"] == 60  # from config global.timeout

    def test_missing_config_flag_shows_error(self):
        runner = CliRunner()
        result = runner.invoke(main, ["sync-all"])
        assert result.exit_code != 0
        assert "config" in result.output.lower() or "missing" in result.output.lower()


# ---------------------------------------------------------------------------
# import-all
# ---------------------------------------------------------------------------


class TestImportAll:
    def test_success_exits_zero(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]), patch(
            "git_mirror.cli.print_summary"
        ):
            result = runner.invoke(main, ["import-all", "-c", config])
        assert result.exit_code == 0

    def test_failure_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_fail()]), patch(
            "git_mirror.cli.print_summary"
        ):
            result = runner.invoke(main, ["import-all", "-c", config])
        assert result.exit_code == 1

    def test_dry_run_propagated(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["import-all", "-c", config, "--dry-run"])
        _, kwargs = mock_rp.call_args
        assert kwargs["dry_run"] is True

    def test_invalid_config_exits_one(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["import-all", "-c", str(tmp_path / "nope.json")])
        assert result.exit_code == 1

    def test_import_repo_fn_is_passed_to_run_parallel(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        from git_mirror import sync as sync_mod

        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["import-all", "-c", config])
        positional_fn = mock_rp.call_args[0][0]
        assert positional_fn is sync_mod.import_repo


# ---------------------------------------------------------------------------
# export-all
# ---------------------------------------------------------------------------


class TestExportAll:
    def test_success_exits_zero(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]), patch(
            "git_mirror.cli.print_summary"
        ):
            result = runner.invoke(main, ["export-all", "-c", config])
        assert result.exit_code == 0

    def test_failure_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("git_mirror.cli.run_parallel", return_value=[_fail()]), patch(
            "git_mirror.cli.print_summary"
        ):
            result = runner.invoke(main, ["export-all", "-c", config])
        assert result.exit_code == 1

    def test_invalid_config_exits_one(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["export-all", "-c", str(tmp_path / "nope.json")])
        assert result.exit_code == 1

    def test_export_repo_fn_is_passed_to_run_parallel(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        from git_mirror import sync as sync_mod

        with patch("git_mirror.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "git_mirror.cli.print_summary"
        ):
            runner.invoke(main, ["export-all", "-c", config])
        positional_fn = mock_rp.call_args[0][0]
        assert positional_fn is sync_mod.export_repo


# ---------------------------------------------------------------------------
# sync (ad-hoc)
# ---------------------------------------------------------------------------


class TestSyncSingle:
    def test_success_prints_message_and_exits_zero(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_ok()):
            result = runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                ],
            )
        assert result.exit_code == 0
        assert "Success" in result.output

    def test_failure_prints_error_and_exits_one(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_fail()):
            result = runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                ],
            )
        assert result.exit_code == 1

    def test_missing_source_exits_nonzero(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["sync", "--dest", "git@backup.example.com:mirrors/proj.git"],
        )
        assert result.exit_code != 0

    def test_missing_dest_exits_nonzero(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["sync", "--source", "git@github.com:org/proj.git"],
        )
        assert result.exit_code != 0

    def test_lfs_flag_propagated(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_ok()) as mock_sync:
            runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                    "--lfs",
                ],
            )
        repo_arg = mock_sync.call_args[0][0]
        assert repo_arg.lfs is True

    def test_custom_name_propagated(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_ok()) as mock_sync:
            runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                    "--name", "my-repo",
                ],
            )
        repo_arg = mock_sync.call_args[0][0]
        assert repo_arg.name == "my-repo"

    def test_timeout_propagated(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_ok()) as mock_sync:
            runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                    "--timeout", "600",
                ],
            )
        _, kwargs = mock_sync.call_args
        assert kwargs["timeout"] == 600

    def test_default_timeout_is_300(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_ok()) as mock_sync:
            runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                ],
            )
        _, kwargs = mock_sync.call_args
        assert kwargs["timeout"] == 300

    def test_dry_run_propagated(self):
        runner = CliRunner()
        with patch("git_mirror.cli.sync_repo", return_value=_ok()) as mock_sync:
            runner.invoke(
                main,
                [
                    "sync",
                    "--source", "git@github.com:org/proj.git",
                    "--dest", "git@backup.example.com:mirrors/proj.git",
                    "--dry-run",
                ],
            )
        _, kwargs = mock_sync.call_args
        assert kwargs["dry_run"] is True
