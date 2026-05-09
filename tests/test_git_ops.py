"""Tests for gitbit.git_ops."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gitbit.exceptions import AuthError, DiskSpaceError, GitOperationError
from gitbit.git_ops import (
    MIN_FREE_GB,
    _run_command,
    check_disk_space,
    clone_mirror,
    fetch_mirror,
    gc_mirror,
    lfs_available,
    lfs_fetch_all,
    lfs_push_all,
    push_mirror,
)


# ---------------------------------------------------------------------------
# _run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_success_returns_completed_process(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(["git", "status"], 0, "ok", "")
        result = _run_command(["git", "status"])
        assert result.returncode == 0
        mock_run.assert_called_once()

    def test_nonzero_exit_raises_git_operation_error(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            ["git", "push"], 128, "", "fatal: not a git repo"
        )
        with pytest.raises(GitOperationError, match="Command failed"):
            _run_command(["git", "push"])

    def test_timeout_raises_git_operation_error(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.side_effect = subprocess.TimeoutExpired(["git", "fetch"], 30)
        with pytest.raises(GitOperationError, match="timed out"):
            _run_command(["git", "fetch"], timeout=30)

    def test_executable_not_found_raises_git_operation_error(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.side_effect = FileNotFoundError("not found")
        with pytest.raises(GitOperationError, match="Executable not found"):
            _run_command(["git-nonexistent", "cmd"])

    def test_dry_run_skips_subprocess(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        result = _run_command(["git", "push", "--mirror", "https://example.com/repo"], dry_run=True)
        mock_run.assert_not_called()
        assert result.returncode == 0

    def test_shell_is_never_true(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(["git", "status"], 0, "", "")
        _run_command(["git", "status"])
        _, kwargs = mock_run.call_args
        assert kwargs.get("shell", False) is False

    def test_auth_failure_stderr_raises_auth_error(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            ["git", "push"], 128, "", "fatal: Authentication failed for 'https://github.com/'"
        )
        with pytest.raises(AuthError, match="Authentication failed"):
            _run_command(["git", "push"])

    def test_permission_denied_raises_auth_error(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            ["git", "fetch"], 128, "", "Permission denied (publickey,gssapi-keyex)"
        )
        with pytest.raises(AuthError):
            _run_command(["git", "fetch"])

    def test_generic_failure_raises_git_operation_error_not_auth_error(self, mocker) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            ["git", "push"], 1, "", "error: failed to push some refs"
        )
        with pytest.raises(GitOperationError):
            _run_command(["git", "push"])

    def test_auth_error_not_retried_by_retryable_run(self, mocker) -> None:
        from gitbit.git_ops import _retryable_run

        call_count = 0

        def mock_subprocess(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args[0], 128, "", "fatal: Authentication failed for 'https://x.com/'"
            )

        mocker.patch("subprocess.run", side_effect=mock_subprocess)
        with pytest.raises(AuthError):
            _retryable_run(["git", "push", "origin"])
        assert call_count == 1  # must not retry

    def test_redact_args_hides_credential_in_log(self, mocker, caplog) -> None:
        import logging

        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(["git", "push"], 0, "", "")
        with caplog.at_level(logging.DEBUG, logger="gitbit.git_ops"):
            _run_command(
                ["git", "push", "--mirror", "https://oauth2:secret@host/repo"],
                redact_args={3},
            )
        assert "secret" not in caplog.text


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------


class TestCheckDiskSpace:
    def test_sufficient_space_does_not_raise(self, tmp_path: Path, mocker) -> None:
        mocker.patch(
            "shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),  # 10 GB
        )
        check_disk_space(str(tmp_path), min_gb=1.0)  # should not raise

    def test_insufficient_space_raises_disk_space_error(self, tmp_path: Path, mocker) -> None:
        mocker.patch(
            "shutil.disk_usage",
            return_value=MagicMock(free=int(0.1 * 1024**3)),  # 100 MB
        )
        with pytest.raises(DiskSpaceError, match="Insufficient disk space"):
            check_disk_space(str(tmp_path), min_gb=1.0)

    def test_walks_up_to_existing_parent(self, tmp_path: Path, mocker) -> None:
        nonexistent = str(tmp_path / "new" / "nested" / "dir")
        mock_usage = mocker.patch(
            "shutil.disk_usage",
            return_value=MagicMock(free=5 * 1024**3),
        )
        check_disk_space(nonexistent)
        # called with an existing ancestor
        called_path = mock_usage.call_args[0][0]
        assert Path(called_path).exists()


# ---------------------------------------------------------------------------
# lfs_available
# ---------------------------------------------------------------------------


class TestLfsAvailable:
    def test_returns_true_when_lfs_installed(self, mocker) -> None:
        mocker.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(["git", "lfs", "version"], 0, "", ""),
        )
        assert lfs_available() is True

    def test_returns_false_when_lfs_not_installed(self, mocker) -> None:
        mocker.patch("subprocess.run", side_effect=FileNotFoundError)
        assert lfs_available() is False

    def test_returns_false_on_nonzero_exit(self, mocker) -> None:
        mocker.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(["git", "lfs", "version"], 1, "", ""),
        )
        assert lfs_available() is False


# ---------------------------------------------------------------------------
# clone_mirror
# ---------------------------------------------------------------------------


class TestCloneMirror:
    def test_calls_git_clone_mirror(self, mocker, tmp_path: Path) -> None:
        mocker.patch("shutil.disk_usage", return_value=MagicMock(free=5 * 1024**3))
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        local_dir = str(tmp_path / "repo.git")
        clone_mirror(
            "git@github.com:org/repo.git",
            local_dir,
            env={},
            timeout=120,
            dry_run=False,
        )
        args = mock_run.call_args[0][0]
        assert args[0] == "git"
        assert "--mirror" in args
        assert local_dir in args

    def test_dry_run_does_not_call_subprocess(self, mocker, tmp_path: Path) -> None:
        mocker.patch("shutil.disk_usage", return_value=MagicMock(free=5 * 1024**3))
        mock_run = mocker.patch("subprocess.run")
        local_dir = str(tmp_path / "repo.git")
        clone_mirror(
            "git@github.com:org/repo.git",
            local_dir,
            env={},
            timeout=120,
            dry_run=True,
        )
        mock_run.assert_not_called()

    def test_raises_disk_space_error_when_low_space(self, mocker, tmp_path: Path) -> None:
        mocker.patch(
            "shutil.disk_usage",
            return_value=MagicMock(free=int(0.5 * 1024**3)),
        )
        mocker.patch("subprocess.run")
        with pytest.raises(DiskSpaceError):
            clone_mirror(
                "git@github.com:org/repo.git",
                str(tmp_path / "repo.git"),
                env={},
                timeout=120,
                dry_run=False,
            )


# ---------------------------------------------------------------------------
# fetch_mirror
# ---------------------------------------------------------------------------


class TestFetchMirror:
    def test_calls_git_remote_update_prune(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        fetch_mirror(str(tmp_path), env={}, timeout=120, dry_run=False)
        args = mock_run.call_args[0][0]
        assert "remote" in args
        assert "update" in args
        assert "--prune" in args

    def test_dry_run_does_not_call_subprocess(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        fetch_mirror(str(tmp_path), env={}, timeout=120, dry_run=True)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# push_mirror
# ---------------------------------------------------------------------------


class TestPushMirror:
    def test_calls_git_push_mirror(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        push_mirror(
            str(tmp_path),
            "git@backup.example.com:mirrors/repo.git",
            env={},
            timeout=120,
            dry_run=False,
        )
        args = mock_run.call_args[0][0]
        assert "push" in args
        assert "--prune" in args
        assert "refs/*" in args
        assert "^refs/merge-requests/*" in args

    def test_dry_run_does_not_call_subprocess(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        push_mirror(
            str(tmp_path),
            "git@backup.example.com:mirrors/repo.git",
            env={},
            timeout=120,
            dry_run=True,
        )
        mock_run.assert_not_called()

    def test_failure_raises_git_operation_error(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 128, "", "fatal: error")
        with pytest.raises(GitOperationError):
            push_mirror(
                str(tmp_path),
                "git@backup.example.com:mirrors/repo.git",
                env={},
                timeout=120,
                dry_run=False,
            )


# ---------------------------------------------------------------------------
# lfs_fetch_all / lfs_push_all
# ---------------------------------------------------------------------------


class TestLfsFetchAll:
    def test_skips_when_lfs_not_available(self, mocker, tmp_path: Path) -> None:
        mocker.patch("gitbit.git_ops.lfs_available", return_value=False)
        mock_run = mocker.patch("subprocess.run")
        lfs_fetch_all(str(tmp_path), env={}, timeout=120, dry_run=False)
        mock_run.assert_not_called()

    def test_calls_git_lfs_fetch_all_when_available(self, mocker, tmp_path: Path) -> None:
        mocker.patch("gitbit.git_ops.lfs_available", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        lfs_fetch_all(str(tmp_path), env={}, timeout=120, dry_run=False)
        args = mock_run.call_args[0][0]
        assert "lfs" in args
        assert "fetch" in args
        assert "--all" in args


class TestLfsPushAll:
    def test_skips_when_lfs_not_available(self, mocker, tmp_path: Path) -> None:
        mocker.patch("gitbit.git_ops.lfs_available", return_value=False)
        mock_run = mocker.patch("subprocess.run")
        lfs_push_all(
            str(tmp_path),
            "git@backup.example.com:mirrors/repo.git",
            env={},
            timeout=120,
            dry_run=False,
        )
        mock_run.assert_not_called()

    def test_calls_git_lfs_push_all_when_available(self, mocker, tmp_path: Path) -> None:
        mocker.patch("gitbit.git_ops.lfs_available", return_value=True)
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        lfs_push_all(
            str(tmp_path),
            "git@backup.example.com:mirrors/repo.git",
            env={},
            timeout=120,
            dry_run=False,
        )
        args = mock_run.call_args[0][0]
        assert "lfs" in args
        assert "push" in args
        assert "--all" in args


# ---------------------------------------------------------------------------
# gc_mirror
# ---------------------------------------------------------------------------


class TestGcMirror:
    def test_calls_git_gc_auto(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        gc_mirror(str(tmp_path))
        args = mock_run.call_args[0][0]
        assert "gc" in args
        assert "--auto" in args

    def test_failure_does_not_raise(self, mocker, tmp_path: Path) -> None:
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess([], 1, "", "error")
        # Should NOT raise; gc failure is non-fatal
        gc_mirror(str(tmp_path))
