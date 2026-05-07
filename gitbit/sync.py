"""High-level sync orchestration for gitbit."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .auth import build_auth_env, inject_https_token, safe_url
from .config import RepoConfig
from .exceptions import GitMirrorError
from . import git_ops

logger = logging.getLogger(__name__)


@dataclass
class RepoResult:
    name: str
    success: bool
    message: str = ""


def _mirrors_path(mirrors_dir: str, name: str) -> str:
    return str(Path(mirrors_dir) / f"{name}.git")


def import_repo(
    repo: RepoConfig,
    mirrors_dir: str,
    *,
    timeout: int,
    dry_run: bool,
) -> RepoResult:
    """Clone or fetch a source repo into a local bare mirror.

    If the local mirror directory already exists, fetches updates (--prune).
    If it does not exist, clones a fresh mirror. Handles LFS if configured.
    """
    local_dir = _mirrors_path(mirrors_dir, repo.name)
    base_env = os.environ.copy()
    env = build_auth_env(repo.auth, base_env)
    src_url = inject_https_token(repo.source, repo.auth)
    try:
        if Path(local_dir).exists():
            logger.info("[%s] Fetching updates into existing mirror", repo.name)
            git_ops.fetch_mirror(local_dir, env=env, timeout=timeout, dry_run=dry_run)
        else:
            logger.info("[%s] Cloning mirror from %s", repo.name, safe_url(src_url))
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
    """Push a local mirror to the destination remote.

    Returns an error result immediately if the local mirror does not exist
    (unless dry_run is True, in which case the push is simulated anyway).
    """
    local_dir = _mirrors_path(mirrors_dir, repo.name)
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
    """Import then export a single repo in sequence.

    Returns immediately with the import failure if the import step fails.
    """
    result = import_repo(repo, mirrors_dir, timeout=timeout, dry_run=dry_run)
    if not result.success:
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
    """Run operation on all repos concurrently using a ThreadPoolExecutor.

    Returns a list of RepoResult in completion order (not submission order).
    Any unexpected exception from a future is caught and wrapped in a failure result.
    """
    results: list[RepoResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(operation, repo, mirrors_dir, timeout=timeout, dry_run=dry_run): repo
            for repo in repos
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.error("[%s] Unexpected error: %s", repo.name, e)
                results.append(RepoResult(name=repo.name, success=False, message=str(e)))
    return results


def print_summary(results: list[RepoResult]) -> None:
    """Log a structured summary of all repo operation results."""
    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    logger.info("Summary: %d succeeded, %d failed", ok, fail)
    for r in results:
        status = "OK" if r.success else "FAIL"
        logger.info("  [%s] %s: %s", status, r.name, r.message)
