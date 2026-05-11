"""CLI integration tests using click.testing.CliRunner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gitbit.cli import main
from gitbit.sync import RepoResult


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
        assert "0.3.3" in result.output

    def test_help_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "gitbit" in result.output

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
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
        ):
            result = runner.invoke(main, ["sync-all", "-c", config])
        assert result.exit_code == 0
        mock_rp.assert_called_once()
        _, kwargs = mock_rp.call_args
        assert kwargs["dry_run"] is False

    def test_all_failures_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_fail()]), patch(
            "gitbit.cli.print_summary"
        ):
            result = runner.invoke(main, ["sync-all", "-c", config])
        assert result.exit_code == 1

    def test_partial_failure_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch(
            "gitbit.cli.run_parallel", return_value=[_ok("R1"), _fail("R2")]
        ), patch("gitbit.cli.print_summary"):
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
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config, "--dry-run"])
        _, kwargs = mock_rp.call_args
        assert kwargs["dry_run"] is True

    def test_parallel_override(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config, "--parallel", "8"])
        _, kwargs = mock_rp.call_args
        assert kwargs["workers"] == 8

    def test_timeout_override(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
        ):
            runner.invoke(main, ["sync-all", "-c", config, "--timeout", "999"])
        _, kwargs = mock_rp.call_args
        assert kwargs["timeout"] == 999

    def test_config_defaults_used_when_no_overrides(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
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
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]), patch(
            "gitbit.cli.print_summary"
        ):
            result = runner.invoke(main, ["import-all", "-c", config])
        assert result.exit_code == 0

    def test_failure_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_fail()]), patch(
            "gitbit.cli.print_summary"
        ):
            result = runner.invoke(main, ["import-all", "-c", config])
        assert result.exit_code == 1

    def test_dry_run_propagated(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
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
        from gitbit import sync as sync_mod

        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
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
        with patch("gitbit.cli.run_parallel", return_value=[_ok()]), patch(
            "gitbit.cli.print_summary"
        ):
            result = runner.invoke(main, ["export-all", "-c", config])
        assert result.exit_code == 0

    def test_failure_exits_one(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_fail()]), patch(
            "gitbit.cli.print_summary"
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
        from gitbit import sync as sync_mod

        with patch("gitbit.cli.run_parallel", return_value=[_ok()]) as mock_rp, patch(
            "gitbit.cli.print_summary"
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
        with patch("gitbit.cli.sync_repo", return_value=_ok()):
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
        with patch("gitbit.cli.sync_repo", return_value=_fail()):
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
        with patch("gitbit.cli.sync_repo", return_value=_ok()) as mock_sync:
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
        with patch("gitbit.cli.sync_repo", return_value=_ok()) as mock_sync:
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
        with patch("gitbit.cli.sync_repo", return_value=_ok()) as mock_sync:
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
        with patch("gitbit.cli.sync_repo", return_value=_ok()) as mock_sync:
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
        with patch("gitbit.cli.sync_repo", return_value=_ok()) as mock_sync:
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


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


class TestValidateCmd:
    def test_valid_config_exits_zero(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.validate_config", return_value=[]):
            result = runner.invoke(main, ["validate", "-c", config])
        assert result.exit_code == 0
        assert "All checks passed" in result.output

    def test_config_errors_exit_one(self, tmp_path):
        from gitbit.config import ValidationIssue
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        issues = [ValidationIssue(field="auth.token_env", message="TOKEN not set",
                                  severity="error", repo="RepoA")]
        with patch("gitbit.cli.validate_config", return_value=issues):
            result = runner.invoke(main, ["validate", "-c", config])
        assert result.exit_code == 1
        assert "[error]" in result.output

    def test_warnings_only_exit_zero(self, tmp_path):
        from gitbit.config import ValidationIssue
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        issues = [ValidationIssue(field="mirrors_dir", message="does not exist",
                                  severity="warning")]
        with patch("gitbit.cli.validate_config", return_value=issues):
            result = runner.invoke(main, ["validate", "-c", config])
        assert result.exit_code == 0
        assert "[warn]" in result.output

    def test_missing_config_exits_one(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["validate", "-c", str(tmp_path / "nope.json")])
        assert result.exit_code == 1

    def test_output_shows_repo_count_and_mirrors_dir(self, tmp_path):
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.validate_config", return_value=[]):
            result = runner.invoke(main, ["validate", "-c", config])
        assert "1 repo(s)" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatusCmd:
    def test_shows_present_and_missing_repos(self, tmp_path):
        from gitbit.sync import RepoStatus
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        statuses = [RepoStatus(name="RepoA", mirror_path="/m/RepoA.git",
                               present=True, size_mb=12.5, last_modified=None)]
        with patch("gitbit.cli.get_repo_status", side_effect=statuses):
            result = runner.invoke(main, ["status", "-c", config])
        assert result.exit_code == 0
        assert "present" in result.output
        assert "RepoA" in result.output

    def test_missing_mirror_shown_as_missing(self, tmp_path):
        from gitbit.sync import RepoStatus
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        statuses = [RepoStatus(name="RepoA", mirror_path="/m/RepoA.git", present=False)]
        with patch("gitbit.cli.get_repo_status", side_effect=statuses):
            result = runner.invoke(main, ["status", "-c", config])
        assert result.exit_code == 0
        assert "missing" in result.output

    def test_missing_config_exits_one(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["status", "-c", str(tmp_path / "nope.json")])
        assert result.exit_code == 1

    def test_summary_line_shows_counts(self, tmp_path):
        from gitbit.sync import RepoStatus
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        statuses = [RepoStatus(name="RepoA", mirror_path="/m/RepoA.git",
                               present=True, size_mb=5.0, last_modified=None)]
        with patch("gitbit.cli.get_repo_status", side_effect=statuses):
            result = runner.invoke(main, ["status", "-c", config])
        assert "1 repo(s)" in result.output

    def test_empty_repos_shows_no_repositories_message(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"global": {"mirrors_dir": str(tmp_path)}, "repos": []}))
        runner = CliRunner()
        result = runner.invoke(main, ["status", "-c", str(p)])
        assert result.exit_code == 0
        assert "No repositories defined" in result.output

    def test_last_modified_shown_when_present(self, tmp_path):
        import time
        from gitbit.sync import RepoStatus
        config = _make_config_file(tmp_path)
        runner = CliRunner()
        ts = time.time() - 90  # 90 seconds ago → "1m ago"
        statuses = [RepoStatus(name="RepoA", mirror_path="/m/RepoA.git",
                               present=True, size_mb=1.0, last_modified=ts)]
        with patch("gitbit.cli.get_repo_status", side_effect=statuses):
            result = runner.invoke(main, ["status", "-c", config])
        assert "ago" in result.output


class TestFormatAge:
    def test_seconds(self):
        from gitbit.cli import _format_age
        import time
        assert "s ago" in _format_age(time.time() - 30)

    def test_minutes(self):
        from gitbit.cli import _format_age
        import time
        assert "m ago" in _format_age(time.time() - 120)

    def test_hours(self):
        from gitbit.cli import _format_age
        import time
        assert "h ago" in _format_age(time.time() - 7200)

    def test_days(self):
        from gitbit.cli import _format_age
        import time
        assert "d ago" in _format_age(time.time() - 172800)


class TestCommandFilter:
    def test_filter_injects_command_into_record(self) -> None:
        from gitbit.cli import _CommandFilter
        import logging

        f = _CommandFilter("sync-all")
        record = logging.LogRecord(
            name="gitbit.sync", level=logging.INFO,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        f.filter(record)
        assert record.command == "sync-all"  # type: ignore[attr-defined]

    def test_filter_is_on_file_handler_not_root_logger(self, tmp_path) -> None:
        """Filter must be on the file handler so propagated records from child
        loggers (e.g. worker threads) have %(command)s injected before formatting."""
        import logging
        from logging.handlers import RotatingFileHandler
        from gitbit.cli import _setup_logging, _CommandFilter

        _setup_logging(verbose=False, command="test-cmd")
        root = logging.getLogger()
        try:
            root_filter_types = [type(f).__name__ for f in root.filters]
            assert "_CommandFilter" not in root_filter_types, (
                "_CommandFilter must NOT be on the root logger; it must be on the "
                "file handler so propagated records from child loggers are covered."
            )
            file_hdlr = next(
                (h for h in root.handlers if isinstance(h, RotatingFileHandler)), None
            )
            assert file_hdlr is not None
            handler_filter_types = [type(f).__name__ for f in file_hdlr.filters]
            assert "_CommandFilter" in handler_filter_types
        finally:
            root.handlers.clear()
            root.filters.clear()

    def test_child_logger_record_gets_command_via_handler_filter(self) -> None:
        """Records from child loggers (gitbit.sync, git_ops) propagating to root
        must have record.command set by the handler filter — not a root logger filter."""
        import logging
        from concurrent.futures import ThreadPoolExecutor
        from logging.handlers import RotatingFileHandler
        from gitbit.cli import _setup_logging

        captured: list = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(getattr(record, "command", "MISSING"))

        _setup_logging(verbose=False, command="sync-all")
        root = logging.getLogger()
        try:
            file_hdlr = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
            capturing = CapturingHandler()
            for f in file_hdlr.filters:
                capturing.addFilter(f)
            root.handlers = [
                h for h in root.handlers if not isinstance(h, RotatingFileHandler)
            ]
            root.addHandler(capturing)

            child = logging.getLogger("gitbit.sync")

            def worker():
                child.info("message from worker thread")

            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(worker).result()

            assert len(captured) == 1
            assert captured[0] == "sync-all", (
                f"Expected 'sync-all' but got {captured[0]!r}. "
                "Filter is likely on the root logger instead of the handler."
            )
        finally:
            root.handlers.clear()
            root.filters.clear()
