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
        assert "0.3.4" in result.output

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


# ---------------------------------------------------------------------------
# _format_sync_age
# ---------------------------------------------------------------------------


class TestFormatSyncAge:
    def test_none_returns_never(self):
        from gitbit.cli import _format_sync_age
        assert _format_sync_age(None) == "never"

    def test_empty_string_returns_never(self):
        from gitbit.cli import _format_sync_age
        assert _format_sync_age("") == "never"

    def test_valid_iso_string_returns_ago(self):
        from gitbit.cli import _format_sync_age
        from datetime import datetime, timedelta
        two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        result = _format_sync_age(two_hours_ago)
        assert "ago" in result

    def test_invalid_format_returns_question_mark(self):
        from gitbit.cli import _format_sync_age
        assert _format_sync_age("not-a-date") == "?"


# ---------------------------------------------------------------------------
# _select_repos
# ---------------------------------------------------------------------------


class TestSelectRepos:
    """Unit tests for _select_repos filter logic."""

    def _make_repos(self, names):
        from gitbit.config import RepoConfig
        return [
            RepoConfig(
                name=n,
                source=f"git@gh.com:org/{n}.git",
                dest=f"git@bk.com:mirrors/{n}.git",
            )
            for n in names
        ]

    def test_no_filters_returns_all_repos(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB", "RepoC"])
        result = _select_repos(repos, (), (), False, {"repos": {}})
        assert [r.name for r in result] == ["RepoA", "RepoB", "RepoC"]

    def test_only_valid_name_returns_single_repo(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        result = _select_repos(repos, ("RepoA",), (), False, {"repos": {}})
        assert result is not None
        assert [r.name for r in result] == ["RepoA"]

    def test_only_unknown_name_returns_none(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        result = _select_repos(repos, ("NonExistent",), (), False, {"repos": {}})
        assert result is None

    def test_exclude_valid_name_removes_repo(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB", "RepoC"])
        result = _select_repos(repos, (), ("RepoB",), False, {"repos": {}})
        assert result is not None
        assert [r.name for r in result] == ["RepoA", "RepoC"]

    def test_exclude_unknown_name_returns_all_repos(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        result = _select_repos(repos, (), ("Ghost",), False, {"repos": {}})
        assert result is not None
        assert [r.name for r in result] == ["RepoA", "RepoB"]

    def test_retry_failed_with_one_failure(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        state = {"repos": {"RepoA": {"last_sync_status": "failed"}}}
        result = _select_repos(repos, (), (), True, state)
        assert result is not None
        assert [r.name for r in result] == ["RepoA"]

    def test_retry_failed_no_failures_returns_empty(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        state = {"repos": {"RepoA": {"last_sync_status": "success"}}}
        result = _select_repos(repos, (), (), True, state)
        assert result == []

    def test_retry_failed_stale_name_not_in_config_is_skipped(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA"])
        state = {"repos": {
            "RepoA": {"last_sync_status": "failed"},
            "OldRepo": {"last_sync_status": "failed"},
        }}
        result = _select_repos(repos, (), (), True, state)
        assert result is not None
        assert [r.name for r in result] == ["RepoA"]

    def test_retry_failed_all_stale_returns_empty(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA"])
        state = {"repos": {"OldRepo": {"last_sync_status": "failed"}}}
        result = _select_repos(repos, (), (), True, state)
        assert result == []

    def test_only_and_exclude_mutually_exclusive(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        result = _select_repos(repos, ("RepoA",), ("RepoB",), False, {"repos": {}})
        assert result is None

    def test_only_and_retry_failed_mutually_exclusive(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        result = _select_repos(repos, ("RepoA",), (), True, {"repos": {}})
        assert result is None

    def test_all_three_flags_mutually_exclusive(self):
        from gitbit.cli import _select_repos
        repos = self._make_repos(["RepoA", "RepoB"])
        result = _select_repos(repos, ("RepoA",), ("RepoB",), True, {"repos": {}})
        assert result is None


# ---------------------------------------------------------------------------
# sync-all / import-all / export-all filter flag integration
# ---------------------------------------------------------------------------


class TestSyncAllFilterFlags:
    """Integration tests for --only / --exclude / --retry-failed on batch commands."""

    def _make_two_repo_config(self, tmp_path):
        return _make_config_file(
            tmp_path,
            repos=[
                {"name": "RepoA", "source": "git@github.com:org/A.git",
                 "dest": "git@backup.example.com:mirrors/A.git", "lfs": False},
                {"name": "RepoB", "source": "git@github.com:org/B.git",
                 "dest": "git@backup.example.com:mirrors/B.git", "lfs": False},
            ],
        )

    def test_only_repoa_passes_just_repoa_to_run_parallel(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel", return_value=[_ok("RepoA")]) as mock_rp, \
             patch("gitbit.cli.print_summary"), \
             patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(main, ["sync-all", "-c", config, "--only", "RepoA"])
        assert result.exit_code == 0
        repos_passed = mock_rp.call_args[0][1]
        assert len(repos_passed) == 1
        assert repos_passed[0].name == "RepoA"

    def test_only_nonexistent_repo_exits_one(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(main, ["sync-all", "-c", config, "--only", "NonExistent"])
        assert result.exit_code == 1

    def test_retry_failed_no_failures_exits_zero_without_run_parallel(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel") as mock_rp, \
             patch("gitbit.cli.print_summary"), \
             patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(main, ["sync-all", "-c", config, "--retry-failed"])
        assert result.exit_code == 0
        mock_rp.assert_not_called()

    def test_only_and_exclude_together_exits_one(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(
                main,
                ["sync-all", "-c", config, "--only", "RepoA", "--exclude", "RepoB"],
            )
        assert result.exit_code == 1

    def test_import_all_only_nonexistent_exits_one(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(
                main, ["import-all", "-c", config, "--only", "NonExistent"]
            )
        assert result.exit_code == 1

    def test_export_all_retry_failed_no_failures_exits_zero(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel") as mock_rp, \
             patch("gitbit.cli.print_summary"), \
             patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(main, ["export-all", "-c", config, "--retry-failed"])
        assert result.exit_code == 0
        mock_rp.assert_not_called()

    def test_import_all_retry_failed_no_failures_exits_zero(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.run_parallel") as mock_rp, \
             patch("gitbit.cli.print_summary"), \
             patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(main, ["import-all", "-c", config, "--retry-failed"])
        assert result.exit_code == 0
        mock_rp.assert_not_called()

    def test_export_all_only_nonexistent_exits_one(self, tmp_path):
        config = self._make_two_repo_config(tmp_path)
        runner = CliRunner()
        with patch("gitbit.cli.load_state", return_value={"repos": {}}), \
             patch("gitbit.cli.save_state"):
            result = runner.invoke(
                main, ["export-all", "-c", config, "--only", "NonExistent"]
            )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Log helpers: _log_files, _parse_since, _read_log_lines, _matches_filters
# ---------------------------------------------------------------------------


class TestLogHelpers:
    # --- _log_files ---

    def test_log_files_no_files_exist(self, tmp_path):
        from gitbit.cli import _log_files
        with patch("gitbit.cli._LOG_FILE", tmp_path / "gitbit.log"):
            files = _log_files()
        assert files == []

    def test_log_files_main_log_exists(self, tmp_path):
        from gitbit.cli import _log_files
        main_log = tmp_path / "gitbit.log"
        main_log.write_text("line\n")
        with patch("gitbit.cli._LOG_FILE", main_log):
            files = _log_files()
        assert files == [main_log]

    def test_log_files_rotated_files_come_before_main(self, tmp_path):
        from gitbit.cli import _log_files
        main_log = tmp_path / "gitbit.log"
        main_log.write_text("main\n")
        rotated1 = tmp_path / "gitbit.log.1"
        rotated1.write_text("rotated1\n")
        rotated2 = tmp_path / "gitbit.log.2"
        rotated2.write_text("rotated2\n")
        with patch("gitbit.cli._LOG_FILE", main_log):
            files = _log_files()
        # Oldest (highest number) first, main last
        assert files[-1] == main_log
        assert rotated1 in files
        assert rotated2 in files
        assert files.index(rotated2) < files.index(rotated1)

    # --- _parse_since ---

    def test_parse_since_minutes(self):
        from gitbit.cli import _parse_since
        from datetime import datetime, timedelta
        result = _parse_since("30m")
        expected = datetime.now() - timedelta(minutes=30)
        assert abs((result - expected).total_seconds()) < 5

    def test_parse_since_hours(self):
        from gitbit.cli import _parse_since
        from datetime import datetime, timedelta
        result = _parse_since("2h")
        expected = datetime.now() - timedelta(hours=2)
        assert abs((result - expected).total_seconds()) < 5

    def test_parse_since_days(self):
        from gitbit.cli import _parse_since
        from datetime import datetime, timedelta
        result = _parse_since("7d")
        expected = datetime.now() - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 5

    def test_parse_since_date_string(self):
        from gitbit.cli import _parse_since
        from datetime import datetime
        result = _parse_since("2026-05-08")
        assert result == datetime(2026, 5, 8)

    def test_parse_since_datetime_string(self):
        from gitbit.cli import _parse_since
        from datetime import datetime
        result = _parse_since("2026-05-08T10:30:00")
        assert result == datetime(2026, 5, 8, 10, 30, 0)

    def test_parse_since_invalid_raises_value_error(self):
        from gitbit.cli import _parse_since
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_since("badvalue")

    # --- _read_log_lines ---

    def test_read_log_lines_reads_all_nonempty_lines(self, tmp_path):
        from gitbit.cli import _read_log_lines
        log_file = tmp_path / "gitbit.log"
        log_file.write_text("line1\nline2\n\nline3\n", encoding="utf-8")
        with patch("gitbit.cli._log_files", return_value=[log_file]):
            lines = _read_log_lines(None)
        assert lines == ["line1", "line2", "line3"]

    def test_read_log_lines_skips_empty_lines(self, tmp_path):
        from gitbit.cli import _read_log_lines
        log_file = tmp_path / "gitbit.log"
        log_file.write_text("\n\n\nonly-line\n\n", encoding="utf-8")
        with patch("gitbit.cli._log_files", return_value=[log_file]):
            lines = _read_log_lines(None)
        assert lines == ["only-line"]

    def test_read_log_lines_filters_old_entries(self, tmp_path):
        from gitbit.cli import _read_log_lines
        from datetime import datetime
        log_file = tmp_path / "gitbit.log"
        log_file.write_text(
            "2026-05-08T10:30:00 INFO     sync-all     [RepoA] old entry\n"
            "2026-05-10T10:30:00 INFO     sync-all     [RepoA] new entry\n",
            encoding="utf-8",
        )
        since_dt = datetime(2026, 5, 9)
        with patch("gitbit.cli._log_files", return_value=[log_file]):
            lines = _read_log_lines(since_dt)
        assert len(lines) == 1
        assert "new entry" in lines[0]

    def test_read_log_lines_oserror_returns_empty(self, tmp_path):
        from gitbit.cli import _read_log_lines
        # A directory cannot be opened as a text file — raises IsADirectoryError (OSError).
        fake_log = tmp_path / "notafile"
        fake_log.mkdir()
        with patch("gitbit.cli._log_files", return_value=[fake_log]):
            lines = _read_log_lines(None)
        assert lines == []

    def test_read_log_lines_invalid_timestamp_still_includes_line(self, tmp_path):
        from gitbit.cli import _read_log_lines
        from datetime import datetime
        log_file = tmp_path / "gitbit.log"
        # month=13 matches the regex digits but strptime raises ValueError
        log_file.write_text(
            "2026-13-45T99:99:99 INFO     sync-all     [RepoA] bad timestamp\n",
            encoding="utf-8",
        )
        since_dt = datetime(2026, 5, 9)
        with patch("gitbit.cli._log_files", return_value=[log_file]):
            lines = _read_log_lines(since_dt)
        # Unparseable timestamp → ValueError caught → line is NOT filtered out
        assert len(lines) == 1
        assert "bad timestamp" in lines[0]

    # --- _matches_filters ---

    SAMPLE_LINE = "2026-05-08T10:30:00 INFO     sync-all     [RepoA] Sync complete"

    def test_matches_filters_no_filters(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters(self.SAMPLE_LINE, 0, None, None) is True

    def test_matches_filters_level_too_high(self):
        from gitbit.cli import _matches_filters
        import logging as _logging
        assert _matches_filters(self.SAMPLE_LINE, _logging.WARNING, None, None) is False

    def test_matches_filters_level_matches(self):
        from gitbit.cli import _matches_filters
        import logging as _logging
        assert _matches_filters(self.SAMPLE_LINE, _logging.INFO, None, None) is True

    def test_matches_filters_cmd_no_match(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters(self.SAMPLE_LINE, 0, "import-all", None) is False

    def test_matches_filters_cmd_matches(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters(self.SAMPLE_LINE, 0, "sync-all", None) is True

    def test_matches_filters_cmd_case_insensitive(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters(self.SAMPLE_LINE, 0, "SYNC-ALL", None) is True

    def test_matches_filters_repo_no_match(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters(self.SAMPLE_LINE, 0, None, "RepoB") is False

    def test_matches_filters_repo_matches(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters(self.SAMPLE_LINE, 0, None, "RepoA") is True

    def test_matches_filters_non_matching_line_format(self):
        from gitbit.cli import _matches_filters
        assert _matches_filters("this is not a log line", 0, None, None) is False


# ---------------------------------------------------------------------------
# logs command
# ---------------------------------------------------------------------------


class TestLogsCmd:
    """End-to-end tests for the `logs` command via CliRunner."""

    _ENTRIES = [
        f"2026-05-08T10:30:0{i} INFO     sync-all     [RepoA] msg{i}"
        for i in range(5)
    ]

    def test_no_log_files_prints_message(self):
        runner = CliRunner()
        with patch("gitbit.cli._log_files", return_value=[]):
            result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        assert "No log file found" in result.output

    def test_has_entries_default_tail_shows_all(self):
        runner = CliRunner()
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=self._ENTRIES):
            result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        for entry in self._ENTRIES:
            assert entry in result.output

    def test_tail_3_shows_only_last_3(self):
        runner = CliRunner()
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=self._ENTRIES):
            result = runner.invoke(main, ["logs", "--tail", "3"])
        assert result.exit_code == 0
        assert "msg0" not in result.output
        assert "msg1" not in result.output
        assert "msg4" in result.output

    def test_tail_0_shows_all(self):
        runner = CliRunner()
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=self._ENTRIES):
            result = runner.invoke(main, ["logs", "--tail", "0"])
        assert result.exit_code == 0
        for entry in self._ENTRIES:
            assert entry in result.output

    def test_no_matching_entries_shows_no_match_message(self):
        runner = CliRunner()
        error_entries = [
            "2026-05-08T10:30:00 ERROR    sync-all     [RepoA] failed"
        ]
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=error_entries):
            result = runner.invoke(main, ["logs", "--level", "ERROR", "--repo", "RepoB"])
        assert result.exit_code == 0
        assert "No log entries match" in result.output

    def test_level_error_filter(self):
        runner = CliRunner()
        mixed_entries = [
            "2026-05-08T10:30:00 INFO     sync-all     [RepoA] info msg",
            "2026-05-08T10:30:01 ERROR    sync-all     [RepoA] error msg",
        ]
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=mixed_entries):
            result = runner.invoke(main, ["logs", "--level", "ERROR"])
        assert result.exit_code == 0
        assert "error msg" in result.output
        assert "info msg" not in result.output

    def test_command_filter(self):
        runner = CliRunner()
        mixed_entries = [
            "2026-05-08T10:30:00 INFO     sync-all     [RepoA] sync msg",
            "2026-05-08T10:30:01 INFO     validate     [RepoA] validate msg",
        ]
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=mixed_entries):
            result = runner.invoke(main, ["logs", "--command", "validate"])
        assert result.exit_code == 0
        assert "validate msg" in result.output
        assert "sync msg" not in result.output

    def test_repo_filter(self):
        runner = CliRunner()
        mixed_entries = [
            "2026-05-08T10:30:00 INFO     sync-all     [RepoA] msg for A",
            "2026-05-08T10:30:01 INFO     sync-all     [RepoB] msg for B",
        ]
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=mixed_entries):
            result = runner.invoke(main, ["logs", "--repo", "RepoA"])
        assert result.exit_code == 0
        assert "msg for A" in result.output
        assert "msg for B" not in result.output

    def test_invalid_since_exits_one(self):
        runner = CliRunner()
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]):
            result = runner.invoke(main, ["logs", "--since", "badvalue"])
        assert result.exit_code == 1

    def test_valid_since_exits_zero(self):
        runner = CliRunner()
        with patch("gitbit.cli._log_files", return_value=[Path("/fake/gitbit.log")]), \
             patch("gitbit.cli._read_log_lines", return_value=self._ENTRIES):
            result = runner.invoke(main, ["logs", "--since", "1h"])
        assert result.exit_code == 0

    def test_follow_exits_cleanly_on_keyboard_interrupt(self, tmp_path):
        """--follow: echoes initial lines, reads new data from tail, exits cleanly on Ctrl-C."""
        from unittest.mock import MagicMock
        existing_line = "2026-05-08T10:30:00 INFO     sync-all     [RepoA] old entry"
        new_line = "2026-05-08T10:31:00 INFO     sync-all     [RepoA] new entry"
        # Mock the live log file handle: first readline returns a new line, second returns ""
        # which triggers time.sleep, which raises KeyboardInterrupt.
        mock_fh = MagicMock()
        mock_fh.readline.side_effect = [new_line + "\n", ""]
        mock_log = MagicMock()
        mock_log.open.return_value.__enter__.return_value = mock_fh
        runner = CliRunner()
        with patch("gitbit.cli._read_log_lines", return_value=[existing_line]), \
             patch("gitbit.cli._LOG_FILE", mock_log), \
             patch("gitbit.cli.time") as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt()
            result = runner.invoke(main, ["logs", "--follow"])
        assert result.exit_code == 0
        assert existing_line in result.output
        assert new_line in result.output
