"""
High-level sync orchestration for gitbit.

This module sits between the CLI layer (cli.py) and the raw Git operations
layer (git_ops.py). It is responsible for:

  1. Translating RepoConfig objects into concrete git operations.
  2. Deciding clone vs. fetch based on local mirror state.
  3. Coordinating the import → export sequence.
  4. Running multiple repos concurrently using a thread pool.
  5. Collecting structured results (RepoResult) without raising exceptions
     at the orchestration level — failures are captured, not propagated.
  6. Reporting mirror state (RepoStatus) without touching the network.

Data flow
---------
For 'gitbit sync-all':

    CLI
    └── run_parallel(sync_repo, repos, ...)
        └── sync_repo(repo, ...)
            ├── import_repo(repo, ...)   → git clone --mirror  (first run)
            │                              git remote update   (subsequent runs)
            │                              git lfs fetch --all (if lfs=True)
            └── export_repo(repo, ...)  → git push --mirror
                                          git lfs push --all  (if lfs=True)

Thread safety
-------------
Each import_repo() / export_repo() call copies os.environ before modifying it
(via build_auth_env), so threads do not share environment dictionaries.

Error handling strategy
-----------------------
Operations return RepoResult(success=False, message=...) on failure rather than
raising. This allows run_parallel() to collect results from all repos even when
some fail, enabling the summary to report the full picture. The CLI layer then
inspects the results and sets the process exit code appropriately.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .auth import build_auth_env, inject_https_token, safe_url
from .config import RepoConfig
from .exceptions import GitMirrorError
from . import git_ops

logger = logging.getLogger(__name__)


@dataclass
class RepoResult:
    """Result of a single repository operation (import, export, or sync).

    Returned by import_repo(), export_repo(), and sync_repo(). Representing
    failures as a value (rather than raising an exception) allows run_parallel()
    to accumulate results from all repos even when individual ones fail, so the
    final summary always covers the complete batch.

    Attributes:
        name:    Repository name (from RepoConfig.name). Used for logging
                 and for associating the result with the original config entry.
        success: True if the operation completed without error. False if any
                 git operation raised GitMirrorError (or an unexpected exception
                 was caught by run_parallel).
        message: Human-readable status string. 'import ok' or 'export ok' on
                 success. The exception message (str(e)) on failure.
    """

    name: str
    success: bool
    message: str = ""


@dataclass
class RepoStatus:
    """Local mirror state for a single repository, computed without network access.

    Returned by get_repo_status() and used by the 'gitbit status' CLI command
    to display a human-readable table of all mirrors at a glance.

    Attributes:
        name:          Repository name (from RepoConfig.name).
        mirror_path:   Absolute path to the expected bare mirror directory
                       (<mirrors_dir>/<name>.git). This path is set regardless
                       of whether it actually exists on disk.
        present:       True if the mirror directory exists on disk.
        size_mb:       Total size of all files under the mirror directory in
                       megabytes. 0.0 when the mirror is absent.
        last_modified: Unix timestamp (float) of the most recently modified
                       file found anywhere under the mirror directory.
                       None if the mirror is absent or contains no files.
    """

    name: str
    mirror_path: str
    present: bool
    size_mb: float = 0.0
    last_modified: Optional[float] = None  # Unix timestamp; None if mirror absent


def _mirrors_path(mirrors_dir: str, name: str) -> str:
    """Compute the absolute path for a named repository's mirror directory.

    Bare git mirrors follow the convention of ending with '.git'. Each repo
    in a batch gets its own subdirectory named after its repo config name.

    Args:
        mirrors_dir: Root directory where all mirror clones are stored.
        name:        Repository name (from RepoConfig.name).

    Returns:
        Absolute path string: <mirrors_dir>/<name>.git
    """
    return str(Path(mirrors_dir) / f"{name}.git")


def _dir_size_mb(path: str) -> float:
    """Recursively calculate the total size of all files under a directory.

    Uses os.walk to traverse the complete directory tree. Individual file
    stat errors (permission denied, file deleted between walk and stat) are
    silently skipped so that a partially readable mirror still returns a
    useful — if slightly understated — size.

    Args:
        path: Root directory to measure. Must exist.

    Returns:
        Total size of all readable files under path, in megabytes.
        Returns 0.0 if the directory is empty or all stat calls fail.
    """
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fname))
            except OSError:
                pass  # File disappeared or is unreadable between walk and stat; skip it
    return total / (1024 * 1024)


def _dir_last_modified(path: str) -> Optional[float]:
    """Find the most recent file modification time anywhere under a directory.

    Walks the full directory tree and tracks the highest mtime seen.
    Individual stat errors are silently skipped.

    Args:
        path: Root directory to scan. Must exist.

    Returns:
        The highest mtime found as a Unix timestamp (float), or None if the
        directory contains no files or all stat calls fail.
    """
    latest: Optional[float] = None
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            try:
                mtime = os.path.getmtime(os.path.join(dirpath, fname))
                if latest is None or mtime > latest:
                    latest = mtime
            except OSError:
                pass  # File disappeared or is unreadable between walk and stat; skip it
    return latest


def get_repo_status(repo: RepoConfig, mirrors_dir: str) -> RepoStatus:
    """Inspect local mirror state for a repository without making network calls.

    Checks whether the expected mirror directory exists on disk, and if so,
    computes its total size and last-modified timestamp by walking the tree.

    Args:
        repo:        Repository configuration. Only repo.name is used here.
        mirrors_dir: Root directory where all mirrors are stored.

    Returns:
        RepoStatus with present=False and zeroed/None fields when the mirror
        directory does not exist. Otherwise returns a fully populated status
        with size_mb and last_modified set from the actual directory contents.
    """
    local_dir = _mirrors_path(mirrors_dir, repo.name)
    if not Path(local_dir).exists():
        return RepoStatus(name=repo.name, mirror_path=local_dir, present=False)
    return RepoStatus(
        name=repo.name,
        mirror_path=local_dir,
        present=True,
        size_mb=_dir_size_mb(local_dir),
        last_modified=_dir_last_modified(local_dir),
    )


def import_repo(
    repo: RepoConfig,
    mirrors_dir: str,
    *,
    timeout: int,
    dry_run: bool,
) -> RepoResult:
    """Fetch a source repository into a local bare mirror.

    Implements the clone-or-fetch decision:
      - If the local mirror directory does NOT exist: runs git clone --mirror
        to create a fresh bare mirror. The parent mirrors_dir is created if
        it does not yet exist (first-run case).
      - If the local mirror directory DOES exist: runs git remote update --prune
        to fetch all new refs and remove deleted ones. No re-clone is needed.

    After cloning or fetching, if repo.lfs is True, also runs git lfs fetch --all
    to download all binary LFS objects from the source.

    Auth is set up per-call: build_auth_env() returns a new dict so each thread
    in a parallel batch has its own copy of the environment.

    Args:
        repo:        Repository configuration (source URL, auth, lfs flag).
        mirrors_dir: Root directory where all mirrors are stored.
        timeout:     Maximum seconds allowed for any single git operation.
        dry_run:     When True, log all commands without executing them.
                     The local mirror existence check is still performed, so
                     dry-run accurately reflects what a real run would do.

    Returns:
        RepoResult(success=True) on completion.
        RepoResult(success=False, message=str(e)) if any GitMirrorError is raised.
    """
    local_dir = _mirrors_path(mirrors_dir, repo.name)

    # Each thread gets its own copy of the environment to avoid race conditions
    # when build_auth_env() adds GIT_SSH_COMMAND.
    base_env = os.environ.copy()
    env = build_auth_env(repo.auth, base_env)

    # Inject the token into the source URL now. The token-embedded URL is only
    # passed to subprocess args — safe_url() is used whenever the URL is logged.
    src_url = inject_https_token(repo.source, repo.auth)

    try:
        if Path(local_dir).exists():
            logger.info("[%s] Fetching updates into existing mirror", repo.name)
            git_ops.fetch_mirror(local_dir, env=env, timeout=timeout, dry_run=dry_run)
        else:
            logger.info("[%s] Cloning mirror from %s", repo.name, safe_url(src_url))
            # Create the mirrors_dir parent if this is the first-ever import.
            # parents=True handles nested paths; exist_ok=True is safe for concurrent runs.
            Path(local_dir).parent.mkdir(parents=True, exist_ok=True)
            git_ops.clone_mirror(src_url, local_dir, env=env, timeout=timeout, dry_run=dry_run)

        if repo.lfs:
            logger.info("[%s] Fetching LFS objects", repo.name)
            git_ops.lfs_fetch_all(local_dir, env=env, timeout=timeout, dry_run=dry_run)

        return RepoResult(name=repo.name, success=True, message="import ok")

    except GitMirrorError as e:
        logger.error("[%s] Import failed: %s", repo.name, e)
        return RepoResult(name=repo.name, success=False, message=str(e))


def export_repo(
    repo: RepoConfig,
    mirrors_dir: str,
    *,
    timeout: int,
    dry_run: bool,
) -> RepoResult:
    """Push a local mirror to the destination repository.

    Requires the local mirror to already exist (i.e. import_repo() was called
    first). If the mirror is missing and dry_run=False, returns an explicit
    failure result with a hint to run import-all first — rather than letting
    git fail with a cryptic error.

    In dry_run mode, the existence check is skipped. This lets --dry-run show
    the full command sequence (clone, fetch, push) for documentation purposes
    even when no local mirrors exist yet.

    After pushing refs via --mirror, if repo.lfs is True, also runs
    git lfs push --all to transfer all LFS object binaries to the destination.

    Args:
        repo:        Repository configuration (destination URL, auth, lfs flag).
        mirrors_dir: Root directory where all mirrors are stored.
        timeout:     Maximum seconds allowed for any single git operation.
        dry_run:     When True, log all commands without executing them, and
                     skip the local mirror existence check.

    Returns:
        RepoResult(success=True) on completion.
        RepoResult(success=False) with an informative message if the local
        mirror is missing (only when dry_run=False).
        RepoResult(success=False, message=str(e)) on any GitMirrorError.
    """
    local_dir = _mirrors_path(mirrors_dir, repo.name)

    # Guard: provide a helpful error instead of a raw git failure when the
    # mirror was never imported. Skipped in dry_run to show the full pipeline.
    if not Path(local_dir).exists() and not dry_run:
        return RepoResult(
            name=repo.name,
            success=False,
            message=f"Local mirror not found at {local_dir}; run import-all first",
        )

    base_env = os.environ.copy()
    dest_env = build_auth_env(repo.auth, base_env)
    dest_url = inject_https_token(repo.dest, repo.auth)

    try:
        logger.info("[%s] Pushing mirror to %s", repo.name, safe_url(dest_url))
        git_ops.push_mirror(local_dir, dest_url, env=dest_env, timeout=timeout, dry_run=dry_run)

        if repo.lfs:
            logger.info("[%s] Pushing LFS objects", repo.name)
            git_ops.lfs_push_all(
                local_dir, dest_url, env=dest_env, timeout=timeout, dry_run=dry_run
            )

        return RepoResult(name=repo.name, success=True, message="export ok")

    except GitMirrorError as e:
        logger.error("[%s] Export failed: %s", repo.name, e)
        return RepoResult(name=repo.name, success=False, message=str(e))


def sync_repo(
    repo: RepoConfig,
    mirrors_dir: str,
    *,
    timeout: int,
    dry_run: bool,
) -> RepoResult:
    """Run a complete import → export cycle for a single repository.

    Calls import_repo() then export_repo() in sequence. If import fails,
    export is skipped — there is no point pushing a mirror we failed to
    import — and the import failure result is returned directly.

    This is the operation used by 'gitbit sync-all' and 'gitbit sync'.

    Args:
        repo:        Repository configuration.
        mirrors_dir: Root directory where all mirrors are stored.
        timeout:     Maximum seconds allowed for any single git operation.
        dry_run:     When True, log all commands without executing them.

    Returns:
        The export RepoResult on success.
        The import RepoResult (success=False) if the import step fails.
    """
    result = import_repo(repo, mirrors_dir, timeout=timeout, dry_run=dry_run)
    if not result.success:
        # Short-circuit: skip export when import failed. The import result
        # already contains the error message the caller needs to report.
        return result
    return export_repo(repo, mirrors_dir, timeout=timeout, dry_run=dry_run)


def run_parallel(
    operation: Callable[..., RepoResult],
    repos: list[RepoConfig],
    mirrors_dir: str,
    *,
    workers: int,
    timeout: int,
    dry_run: bool,
) -> list[RepoResult]:
    """Execute a sync operation on multiple repositories concurrently.

    Uses a ThreadPoolExecutor to process up to `workers` repos in parallel.
    Git operations are network/disk I/O bound, so threading gives real
    concurrency even with CPython's GIL.

    Results arrive in completion order (not submission order) because
    as_completed() is used — faster repos appear in the results list first.
    All repos are processed regardless of individual failures; one repo's
    failure does not cancel or skip others.

    Unexpected exceptions from futures (bugs in operation code, not git
    failures — those are captured inside import/export_repo) are caught and
    wrapped in failure RepoResult objects so they surface in the summary
    rather than being silently lost.

    Args:
        operation:   Callable with signature:
                       (repo: RepoConfig, mirrors_dir: str, *, timeout: int,
                        dry_run: bool) -> RepoResult
                     Typically sync_repo, import_repo, or export_repo.
        repos:       List of repositories to process. May be empty.
        mirrors_dir: Root directory where all mirrors are stored.
        workers:     Maximum number of concurrent threads. Sourced from
                     GlobalConfig.parallel or the --parallel CLI flag.
        timeout:     Maximum seconds per git operation, forwarded to operation.
        dry_run:     Forwarded verbatim to operation.

    Returns:
        List of RepoResult, one per repo, in completion order (not input order).
        The list has the same length as repos.
    """
    results: list[RepoResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Submit all repos immediately and keep a future→repo mapping so we can
        # attribute results (and exceptions) to the correct repo name even after
        # the futures complete out of order.
        futures = {
            pool.submit(operation, repo, mirrors_dir, timeout=timeout, dry_run=dry_run): repo
            for repo in repos
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                # This branch handles unexpected programming errors that escaped
                # the operation's own try/except. GitMirrorError subclasses are
                # captured inside import_repo/export_repo and returned as
                # RepoResult(success=False), so they do not reach here normally.
                logger.error("[%s] Unexpected error: %s", repo.name, e)
                results.append(RepoResult(name=repo.name, success=False, message=str(e)))
    return results


def print_summary(results: list[RepoResult]) -> None:
    """Log a structured summary of all repository operation results.

    Emits two sections to the INFO logger:
      1. A single-line totals line: "Summary: N succeeded, M failed"
      2. One line per repo: "[OK|FAIL] <name>: <message>"

    All output goes through the logger (not print/click.echo) so it respects
    the --verbose flag and the configured log format.

    Args:
        results: List of RepoResult from run_parallel() or a direct call to
                 import/export/sync_repo.
    """
    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    logger.info("Summary: %d succeeded, %d failed", ok, fail)
    for r in results:
        status = "OK" if r.success else "FAIL"
        logger.info("  [%s] %s: %s", status, r.name, r.message)
