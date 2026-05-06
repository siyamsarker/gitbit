"""Core Git operations for git-mirror using subprocess (no shell=True)."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from .exceptions import DiskSpaceError, GitOperationError

logger = logging.getLogger(__name__)

MIN_FREE_GB = 1.0  # require at least 1 GB free before cloning


def _run_command(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    dry_run: bool = False,
    redact_args: set[int] | None = None,
) -> subprocess.CompletedProcess:
    """Run a git command, raising GitOperationError on failure.

    Never uses shell=True. Credentials are redacted from debug output via redact_args.
    """
    display_cmd = list(cmd)
    if redact_args:
        for i in redact_args:
            if i < len(display_cmd):
                display_cmd[i] = "***"
    logger.debug("Running: %s (cwd=%s)", " ".join(display_cmd), cwd)
    if dry_run:
        logger.info("[DRY-RUN] Would run: %s", " ".join(display_cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GitOperationError(
            f"Command timed out after {timeout}s: {' '.join(display_cmd)}"
        ) from e
    except FileNotFoundError as e:
        raise GitOperationError(f"Executable not found: {cmd[0]}") from e
    if result.returncode != 0:
        raise GitOperationError(
            f"Command failed (exit {result.returncode}): {' '.join(display_cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result


def check_disk_space(path: str, min_gb: float = MIN_FREE_GB) -> None:
    """Raise DiskSpaceError if free space at path is below min_gb.

    Walks up the path tree to find the first existing ancestor directory.
    """
    parent = Path(path)
    while not parent.exists():
        parent = parent.parent
    usage = shutil.disk_usage(str(parent))
    free_gb = usage.free / (1024**3)
    if free_gb < min_gb:
        raise DiskSpaceError(
            f"Insufficient disk space at {parent}: {free_gb:.2f} GB free, need {min_gb} GB"
        )


def lfs_available() -> bool:
    """Return True if git-lfs is installed and accessible."""
    try:
        result = subprocess.run(["git", "lfs", "version"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _retryable_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Wrap _run_command with tenacity retry using exponential backoff + jitter.

    Retries up to 5 times on GitOperationError. Waits between 4s and 60s with
    random jitter to avoid thundering-herd on a flaky remote.
    """

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60) + wait_random(0, 3),
        retry=retry_if_exception_type(GitOperationError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _inner() -> subprocess.CompletedProcess:
        return _run_command(cmd, **kwargs)

    return _inner()


def clone_mirror(
    src_url: str,
    local_dir: str,
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> None:
    """Clone source as a bare mirror into local_dir.

    Checks disk space first; then runs: git clone --mirror <src_url> <local_dir>
    """
    check_disk_space(local_dir, MIN_FREE_GB)
    _retryable_run(
        ["git", "clone", "--mirror", src_url, local_dir],
        env=env,
        timeout=timeout,
        dry_run=dry_run,
    )


def fetch_mirror(
    local_dir: str,
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> None:
    """Fetch all updates into an existing mirror clone.

    Runs: git remote update --prune
    """
    _retryable_run(
        ["git", "remote", "update", "--prune"],
        cwd=local_dir,
        env=env,
        timeout=timeout,
        dry_run=dry_run,
    )


def push_mirror(
    local_dir: str,
    dest_url: str,
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> None:
    """Push all refs to destination using --mirror.

    Runs: git push --mirror <dest_url>
    """
    _retryable_run(
        ["git", "push", "--mirror", dest_url],
        cwd=local_dir,
        env=env,
        timeout=timeout,
        dry_run=dry_run,
    )


def lfs_fetch_all(
    local_dir: str,
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> None:
    """Fetch all LFS objects from source.

    No-op with a warning if git-lfs is not installed.
    """
    if not lfs_available():
        logger.warning("git-lfs not found, skipping LFS fetch")
        return
    _retryable_run(
        ["git", "lfs", "fetch", "--all"],
        cwd=local_dir,
        env=env,
        timeout=timeout,
        dry_run=dry_run,
    )


def lfs_push_all(
    local_dir: str,
    dest_url: str,
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> None:
    """Push all LFS objects to destination.

    No-op with a warning if git-lfs is not installed.
    """
    if not lfs_available():
        logger.warning("git-lfs not found, skipping LFS push")
        return
    _retryable_run(
        ["git", "lfs", "push", "--all", dest_url],
        cwd=local_dir,
        env=env,
        timeout=timeout,
        dry_run=dry_run,
    )


def gc_mirror(local_dir: str, *, timeout: int = 120) -> None:
    """Run git gc --auto on the mirror repo to reclaim space.

    Failures are logged as warnings and do not propagate — gc is best-effort.
    """
    try:
        _run_command(["git", "gc", "--auto"], cwd=local_dir, timeout=timeout)
    except GitOperationError as e:
        logger.warning("git gc failed (non-fatal): %s", e)
