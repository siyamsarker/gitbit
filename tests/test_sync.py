"""Tests for gitbit.sync."""
from __future__ import annotations

from pathlib import Path

import pytest

from gitbit.config import AuthConfig, RepoConfig
from gitbit.exceptions import GitOperationError
from gitbit.sync import (
    RepoResult,
    export_repo,
    import_repo,
    print_summary,
    run_parallel,
    sync_repo,
)


def _make_repo(name: str = "TestRepo", lfs: bool = False) -> RepoConfig:
    return RepoConfig(
        name=name,
        source="git@github.com:org/test.git",
        dest="git@backup.example.com:mirrors/test.git",
        lfs=lfs,
    )


# ---------------------------------------------------------------------------
# import_repo
# ---------------------------------------------------------------------------


class TestImportRepo:
    def test_clones_when_local_dir_missing(self, mocker, tmp_path: Path) -> None:
        mock_clone = mocker.patch("gitbit.sync.git_ops.clone_mirror")
        mock_fetch = mocker.patch("gitbit.sync.git_ops.fetch_mirror")
        repo = _make_repo()
        result = import_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_clone.assert_called_once()
        mock_fetch.assert_not_called()
        assert result.success is True
        assert result.name == "TestRepo"

    def test_fetches_when_local_dir_exists(self, mocker, tmp_path: Path) -> None:
        mock_clone = mocker.patch("gitbit.sync.git_ops.clone_mirror")
        mock_fetch = mocker.patch("gitbit.sync.git_ops.fetch_mirror")
        # Create the mirror directory so it appears to exist
        local_dir = tmp_path / "TestRepo.git"
        local_dir.mkdir()
        repo = _make_repo()
        result = import_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_fetch.assert_called_once()
        mock_clone.assert_not_called()
        assert result.success is True

    def test_lfs_fetch_called_when_lfs_true(self, mocker, tmp_path: Path) -> None:
        mocker.patch("gitbit.sync.git_ops.clone_mirror")
        mock_lfs = mocker.patch("gitbit.sync.git_ops.lfs_fetch_all")
        repo = _make_repo(lfs=True)
        result = import_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_lfs.assert_called_once()
        assert result.success is True

    def test_lfs_fetch_not_called_when_lfs_false(self, mocker, tmp_path: Path) -> None:
        mocker.patch("gitbit.sync.git_ops.clone_mirror")
        mock_lfs = mocker.patch("gitbit.sync.git_ops.lfs_fetch_all")
        repo = _make_repo(lfs=False)
        import_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_lfs.assert_not_called()

    def test_git_operation_error_returns_failure_result(self, mocker, tmp_path: Path) -> None:
        mocker.patch(
            "gitbit.sync.git_ops.clone_mirror",
            side_effect=GitOperationError("clone failed"),
        )
        repo = _make_repo()
        result = import_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        assert result.success is False
        assert "clone failed" in result.message

    def test_dry_run_still_returns_success(self, mocker, tmp_path: Path) -> None:
        mock_clone = mocker.patch("gitbit.sync.git_ops.clone_mirror")
        repo = _make_repo()
        result = import_repo(repo, str(tmp_path), timeout=60, dry_run=True)
        mock_clone.assert_called_once()
        assert result.success is True


# ---------------------------------------------------------------------------
# export_repo
# ---------------------------------------------------------------------------


class TestExportRepo:
    def test_push_called_when_local_dir_exists(self, mocker, tmp_path: Path) -> None:
        local_dir = tmp_path / "TestRepo.git"
        local_dir.mkdir()
        mock_push = mocker.patch("gitbit.sync.git_ops.push_mirror")
        repo = _make_repo()
        result = export_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_push.assert_called_once()
        assert result.success is True

    def test_returns_failure_when_local_dir_missing(self, tmp_path: Path) -> None:
        repo = _make_repo()
        result = export_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        assert result.success is False
        assert "not found" in result.message.lower() or "import-all" in result.message

    def test_dry_run_skips_existence_check(self, mocker, tmp_path: Path) -> None:
        # local_dir does NOT exist but dry_run=True — should still proceed
        mock_push = mocker.patch("gitbit.sync.git_ops.push_mirror")
        repo = _make_repo()
        result = export_repo(repo, str(tmp_path), timeout=60, dry_run=True)
        mock_push.assert_called_once()
        assert result.success is True

    def test_lfs_push_called_when_lfs_true(self, mocker, tmp_path: Path) -> None:
        local_dir = tmp_path / "LFSRepo.git"
        local_dir.mkdir()
        mocker.patch("gitbit.sync.git_ops.push_mirror")
        mock_lfs = mocker.patch("gitbit.sync.git_ops.lfs_push_all")
        repo = _make_repo(name="LFSRepo", lfs=True)
        result = export_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_lfs.assert_called_once()
        assert result.success is True

    def test_lfs_push_not_called_when_lfs_false(self, mocker, tmp_path: Path) -> None:
        local_dir = tmp_path / "TestRepo.git"
        local_dir.mkdir()
        mocker.patch("gitbit.sync.git_ops.push_mirror")
        mock_lfs = mocker.patch("gitbit.sync.git_ops.lfs_push_all")
        repo = _make_repo(lfs=False)
        export_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_lfs.assert_not_called()

    def test_push_failure_returns_failure_result(self, mocker, tmp_path: Path) -> None:
        local_dir = tmp_path / "TestRepo.git"
        local_dir.mkdir()
        mocker.patch(
            "gitbit.sync.git_ops.push_mirror",
            side_effect=GitOperationError("push failed"),
        )
        repo = _make_repo()
        result = export_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        assert result.success is False
        assert "push failed" in result.message


# ---------------------------------------------------------------------------
# sync_repo
# ---------------------------------------------------------------------------


class TestSyncRepo:
    def test_sync_calls_import_then_export(self, mocker, tmp_path: Path) -> None:
        mock_import = mocker.patch(
            "gitbit.sync.import_repo",
            return_value=RepoResult(name="R", success=True, message="import ok"),
        )
        mock_export = mocker.patch(
            "gitbit.sync.export_repo",
            return_value=RepoResult(name="R", success=True, message="export ok"),
        )
        repo = _make_repo()
        result = sync_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_import.assert_called_once()
        mock_export.assert_called_once()
        assert result.success is True

    def test_sync_short_circuits_on_import_failure(self, mocker, tmp_path: Path) -> None:
        mocker.patch(
            "gitbit.sync.import_repo",
            return_value=RepoResult(name="R", success=False, message="import failed"),
        )
        mock_export = mocker.patch("gitbit.sync.export_repo")
        repo = _make_repo()
        result = sync_repo(repo, str(tmp_path), timeout=60, dry_run=False)
        mock_export.assert_not_called()
        assert result.success is False
        assert "import failed" in result.message


# ---------------------------------------------------------------------------
# run_parallel
# ---------------------------------------------------------------------------


class TestRunParallel:
    def test_runs_all_repos(self, mocker, tmp_path: Path) -> None:
        repos = [_make_repo(f"Repo{i}") for i in range(3)]

        def fake_op(repo, mirrors_dir, *, timeout, dry_run):
            return RepoResult(name=repo.name, success=True, message="ok")

        results = run_parallel(fake_op, repos, str(tmp_path), workers=2, timeout=60, dry_run=False)
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_captures_unexpected_exceptions(self, tmp_path: Path) -> None:
        repos = [_make_repo("BadRepo")]

        def exploding_op(repo, mirrors_dir, *, timeout, dry_run):
            raise RuntimeError("unexpected boom")

        results = run_parallel(
            exploding_op, repos, str(tmp_path), workers=1, timeout=60, dry_run=False
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "unexpected boom" in results[0].message

    def test_partial_failures_recorded(self, tmp_path: Path) -> None:
        repos = [_make_repo("Good"), _make_repo("Bad")]

        def mixed_op(repo, mirrors_dir, *, timeout, dry_run):
            if repo.name == "Bad":
                return RepoResult(name=repo.name, success=False, message="failed")
            return RepoResult(name=repo.name, success=True, message="ok")

        results = run_parallel(mixed_op, repos, str(tmp_path), workers=2, timeout=60, dry_run=False)
        assert len(results) == 2
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        assert len(successes) == 1
        assert len(failures) == 1


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_logs_summary_without_raising(self, caplog) -> None:
        import logging

        results = [
            RepoResult(name="A", success=True, message="ok"),
            RepoResult(name="B", success=False, message="err"),
        ]
        with caplog.at_level(logging.INFO, logger="gitbit.sync"):
            print_summary(results)
        assert "1 succeeded" in caplog.text
        assert "1 failed" in caplog.text
