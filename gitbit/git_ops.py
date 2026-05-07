"""
Core Git subprocess wrappers for gitbit.

This is the only module in the project that spawns git as a child process.
Keeping all subprocess calls here provides a single place to enforce security
and reliability invariants that must hold for every git operation.

Security guarantees
-------------------
  shell=False always
      Every subprocess.run() call receives a list of arguments, never a string
      with shell=True. This prevents shell injection attacks even if a URL or
      path contains shell metacharacters.

  Credential redaction
      The redact_args parameter in _run_command() replaces specified argument
      positions with '***' in debug log output. Use it for any argument that
      may contain a token or password embedded in a URL.

Reliability guarantees
----------------------
  Retry with exponential backoff + jitter (_retryable_run)
      Network operations (clone, fetch, push, LFS) go through _retryable_run(),
      which retries GitOperationError up to 5 times. Wait time starts at 4s,
      doubles each attempt up to 60s, with 0-3s random jitter to prevent
      thundering-herd when many repos fail simultaneously.

  Auth failure fast-fail
      If git's stderr matches any pattern in _AUTH_FAILURE_PATTERNS, an AuthError
      is raised instead of GitOperationError. The retry decorator only catches
      GitOperationError, so auth failures propagate immediately without retrying.
      This is intentional: a bad credential never succeeds on retry, and retrying
      could trigger rate limits or temporary account locks.

  Disk space pre-flight
      check_disk_space() is called before git clone --mirror. If the target
      filesystem has less than MIN_FREE_GB free, a DiskSpaceError is raised
      before any data transfer starts, preventing partial clones.

Public API (called by sync.py)
-------------------------------
  clone_mirror()     — git clone --mirror
  fetch_mirror()     — git remote update --prune
  push_mirror()      — git push --prune refs/* (excludes GitLab hidden refs)
  lfs_fetch_all()    — git lfs fetch --all
  lfs_push_all()     — git lfs push --all
  gc_mirror()        — git gc --auto (best-effort, non-fatal)
  check_disk_space() — pre-flight disk space guard
  lfs_available()    — probe whether git-lfs is installed
"""
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

from .exceptions import AuthError, DiskSpaceError, GitOperationError

logger = logging.getLogger(__name__)

# Minimum free disk space required before starting a git clone --mirror.
# 1 GB is a conservative lower bound; real repositories vary widely in size.
MIN_FREE_GB = 1.0

# Lowercase substrings matched against git's stderr to classify a failure as
# an authentication error rather than a generic/transient git error.
# Auth errors bypass retry logic — see _retryable_run() for details.
_AUTH_FAILURE_PATTERNS = (
    "authentication failed",
    "permission denied (publickey",
    "could not read username",
    "invalid username or password",
    "remote: invalid username or password",
    "fatal: could not read password",
    "http basic: access denied",
    "the requested url returned error: 401",
    "the requested url returned error: 403",
)


def _run_command(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    dry_run: bool = False,
    redact_args: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a git command as a subprocess and return the completed result.

    This is the lowest-level command runner. All git calls in this module pass
    through here. It enforces the non-negotiable invariants:

      - shell=False at all times.
      - Sensitive argument values are replaced with '***' in log output.
      - In dry-run mode the command is logged but never executed.
      - Non-zero exit codes raise AuthError (for auth failures) or
        GitOperationError (for everything else).
      - Timeouts and missing executables are wrapped into GitOperationError.

    Args:
        cmd:         The command and arguments as a list, e.g.
                     ['git', 'clone', '--mirror', 'https://...', '/path/to/dir'].
                     Never pass a single shell string.
        cwd:         Working directory for the subprocess. Defaults to the
                     current process working directory when None.
        env:         Full environment dict for the subprocess. When None,
                     the subprocess inherits the current process environment.
                     Pass os.environ.copy() (possibly augmented by build_auth_env)
                     to control the exact environment the git process sees.
        timeout:     Seconds to wait before killing the process and raising
                     GitOperationError. Defaults to 300 s (5 minutes).
        dry_run:     When True, log the command at INFO level and return a
                     synthetic success result without spawning a process.
        redact_args: Set of zero-based argument indices to replace with '***'
                     in log output. Use to prevent secrets (e.g. tokens embedded
                     in URLs) from appearing in debug traces.

    Returns:
        subprocess.CompletedProcess with stdout and stderr captured as decoded
        strings (text=True).

    Raises:
        AuthError:         If git exits non-zero and its stderr matches any
                           pattern in _AUTH_FAILURE_PATTERNS.
        GitOperationError: If git exits non-zero for any other reason, if the
                           operation exceeds the timeout, or if the git
                           executable is not found on PATH.
    """
    # Build a display-safe copy of the command by masking sensitive argument
    # positions. This copy is only used for logging; the original cmd is passed
    # to subprocess.run() unchanged.
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
            capture_output=True,   # Capture stdout and stderr separately
            text=True,             # Decode output as UTF-8 strings
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GitOperationError(
            f"Command timed out after {timeout}s: {' '.join(display_cmd)}"
        ) from e
    except FileNotFoundError as e:
        raise GitOperationError(f"Executable not found: {cmd[0]}") from e

    if result.returncode != 0:
        stderr_lower = result.stderr.lower()
        # Check for auth patterns before raising the generic error. AuthError
        # is a sibling of GitOperationError (not a subclass), so the tenacity
        # retry decorator in _retryable_run() will NOT catch it — the error
        # propagates immediately, skipping all retry attempts.
        if any(p in stderr_lower for p in _AUTH_FAILURE_PATTERNS):
            raise AuthError(
                f"Authentication failed (exit {result.returncode}): {' '.join(display_cmd)}\n"
                f"stderr: {result.stderr.strip()}"
            )
        raise GitOperationError(
            f"Command failed (exit {result.returncode}): {' '.join(display_cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )

    return result


def check_disk_space(path: str, min_gb: float = MIN_FREE_GB) -> None:
    """Verify sufficient free disk space exists before starting a clone.

    Walks up the directory tree from path until it finds an existing ancestor,
    then queries disk usage on that filesystem. This correctly handles the case
    where the target directory (or its parent mirrors_dir) does not yet exist.

    Args:
        path:   The target path for the clone. Does not need to exist.
        min_gb: Minimum required free space in gigabytes. Defaults to MIN_FREE_GB.

    Raises:
        DiskSpaceError: If the filesystem that would contain path has less than
                        min_gb free at the time of the check.
    """
    # Walk up to find the first existing directory to query disk usage on.
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
    """Check whether git-lfs is installed and functional on this system.

    Runs 'git lfs version' with a 10-second timeout and inspects the exit code.
    Called as a guard before any LFS operation — if git-lfs is absent, LFS
    steps are skipped with a warning rather than failing hard.

    Returns:
        True if 'git lfs version' exits 0. False if the command is not found,
        times out, or returns a non-zero exit code.
    """
    try:
        result = subprocess.run(["git", "lfs", "version"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _retryable_run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    dry_run: bool = False,
    redact_args: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Wrap _run_command with tenacity retry logic for transient failures.

    Uses tenacity to retry on GitOperationError up to 5 times. The wait
    strategy combines exponential backoff (doubles from 4s to 60s) with
    random jitter (0-3s) to avoid all workers retrying at the same moment
    when a flaky remote affects multiple repos simultaneously.

    Retry schedule (approximate, before jitter):
      Attempt 1: immediate
      Attempt 2: ~4s wait
      Attempt 3: ~8s wait
      Attempt 4: ~16s wait
      Attempt 5: ~32s wait (capped at 60s)

    AuthError is intentionally NOT in the retry condition. It is a sibling
    class of GitOperationError, not a subclass, so tenacity's
    retry_if_exception_type(GitOperationError) does not catch it. Auth failures
    propagate immediately after the first attempt.

    Args:
        cmd:         The git command list to execute.
        cwd:         Working directory for the subprocess.
        env:         Subprocess environment dict.
        timeout:     Maximum seconds per attempt.
        dry_run:     When True, log without executing.
        redact_args: Argument indices to mask in log output.

    Returns:
        subprocess.CompletedProcess on success (possibly after retries).

    Raises:
        AuthError:         Immediately on the first auth failure.
        GitOperationError: After all 5 retry attempts have been exhausted.
    """

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60) + wait_random(0, 3),
        retry=retry_if_exception_type(GitOperationError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _inner() -> subprocess.CompletedProcess[str]:
        return _run_command(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            dry_run=dry_run,
            redact_args=redact_args,
        )

    return _inner()


def clone_mirror(
    src_url: str,
    local_dir: str,
    *,
    env: dict[str, str],
    timeout: int,
    dry_run: bool,
) -> None:
    """Clone a remote repository as a bare mirror into a local directory.

    Performs a disk space pre-flight check, then runs:
        git clone --mirror <src_url> <local_dir>

    The --mirror flag creates a bare clone and configures the remote so that
    'git remote update' can later fetch all updated refs. Importantly, it
    replicates every ref — branches, tags, notes, and replace refs — not just
    the default branch. The resulting directory ends with '.git' by convention.

    Args:
        src_url:   Source repository URL (may contain injected HTTPS credentials).
        local_dir: Absolute path for the new bare mirror directory.
        env:       Subprocess environment dict (with GIT_SSH_COMMAND if using SSH).
        timeout:   Maximum seconds before aborting with GitOperationError.
        dry_run:   When True, log the command without executing it.

    Raises:
        DiskSpaceError:    If free space at local_dir is below MIN_FREE_GB.
        AuthError:         If git reports an authentication failure.
        GitOperationError: If git clone fails after all retry attempts.
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
    """Update an existing bare mirror by fetching all changes from the remote.

    Runs from within the mirror directory:
        git remote update --prune

    'git remote update' fetches all refs from all configured remotes (a mirror
    clone has exactly one remote, 'origin'). The --prune flag removes any local
    refs that no longer exist on the remote, keeping the mirror in sync with
    branch deletions and tag removals on the source.

    Args:
        local_dir: Path to the existing bare mirror directory (.git directory).
        env:       Subprocess environment dict (with GIT_SSH_COMMAND if using SSH).
        timeout:   Maximum seconds before aborting with GitOperationError.
        dry_run:   When True, log the command without executing it.

    Raises:
        AuthError:         If git reports an authentication failure.
        GitOperationError: If the fetch fails after all retry attempts.
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
    """Push all standard refs from a local mirror to a destination repository.

    Runs from within the mirror directory:
        git push --prune <dest_url> refs/* ^refs/merge-requests/* \
            ^refs/pipelines/* ^refs/environments/* ^refs/keep-around/*

    Uses explicit refspecs with negative exclusions (requires Git 2.29+) instead
    of --mirror. This is functionally equivalent for standard ref namespaces but
    skips GitLab-internal hidden refs (merge-requests, pipelines, environments,
    keep-around) that GitLab rejects with "deny updating a hidden ref" when pushed
    to a destination repository.

    --prune ensures refs deleted on the source are also removed from the
    destination, preserving the same deletion semantics as --mirror.

    Args:
        local_dir: Path to the local bare mirror directory.
        dest_url:  Destination repository URL (may contain injected credentials).
        env:       Subprocess environment dict (with GIT_SSH_COMMAND if using SSH).
        timeout:   Maximum seconds before aborting with GitOperationError.
        dry_run:   When True, log the command without executing it.

    Raises:
        AuthError:         If git reports an authentication failure.
        GitOperationError: If git push fails after all retry attempts.
    """
    _retryable_run(
        [
            "git", "push", "--prune", dest_url,
            "refs/*",
            "^refs/merge-requests/*",
            "^refs/pipelines/*",
            "^refs/environments/*",
            "^refs/keep-around/*",
        ],
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
    """Download all Git LFS objects from the remote source into the local mirror.

    Runs from within the mirror directory:
        git lfs fetch --all

    The --all flag fetches every LFS object referenced by any ref in the
    repository, not just objects reachable from HEAD. This is necessary for a
    complete mirror that must be able to reconstruct any historical commit.

    This function is a no-op with a WARNING log if git-lfs is not installed on
    the system. The calling code (import_repo) only calls this when repo.lfs=True,
    so users who do not use LFS never see this warning.

    Args:
        local_dir: Path to the local bare mirror directory.
        env:       Subprocess environment dict (with GIT_SSH_COMMAND if using SSH).
        timeout:   Maximum seconds before aborting with GitOperationError.
        dry_run:   When True, log the command without executing it.

    Raises:
        AuthError:         If git reports an authentication failure.
        GitOperationError: If the LFS fetch fails after all retry attempts.
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
    """Push all Git LFS objects from the local mirror to a destination.

    Runs from within the mirror directory:
        git lfs push --all <dest_url>

    Transfers the binary content of every LFS object stored in the local
    mirror's LFS cache to the destination's LFS server. This should be called
    after push_mirror() so the destination already has the ref structure that
    the LFS objects are associated with.

    This function is a no-op with a WARNING log if git-lfs is not installed.

    Args:
        local_dir: Path to the local bare mirror directory.
        dest_url:  Destination repository URL (may contain injected credentials).
        env:       Subprocess environment dict (with GIT_SSH_COMMAND if using SSH).
        timeout:   Maximum seconds before aborting with GitOperationError.
        dry_run:   When True, log the command without executing it.

    Raises:
        AuthError:         If git reports an authentication failure.
        GitOperationError: If the LFS push fails after all retry attempts.
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
    """Run garbage collection on a local mirror to reclaim disk space.

    Runs from within the mirror directory:
        git gc --auto

    The --auto flag instructs git to only run full GC if internal heuristics
    determine the repository has accumulated enough loose objects or packfiles
    to warrant it. This makes the call cheap when run frequently (e.g. after
    every sync) and effective when the repo genuinely needs compaction.

    Failures are caught, logged at WARNING level, and silently swallowed. GC
    is a housekeeping step; its failure must never abort or fail a sync pipeline.

    Args:
        local_dir: Path to the local bare mirror directory.
        timeout:   Maximum seconds before giving up. Defaults to 120 seconds.
                   GC is not retried — a single best-effort attempt is made.
    """
    try:
        _run_command(["git", "gc", "--auto"], cwd=local_dir, timeout=timeout)
    except GitOperationError as e:
        # GC failure is explicitly non-fatal. Log for visibility but do not
        # propagate — the mirror data itself is unaffected by a GC failure.
        logger.warning("git gc failed (non-fatal): %s", e)
