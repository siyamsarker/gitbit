"""Click-based CLI entry point for git-mirror."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from . import __version__
from .config import RepoConfig, load_config
from .exceptions import GitMirrorError
from .sync import export_repo, import_repo, print_summary, run_parallel, sync_repo


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )


@click.group()
@click.version_option(__version__, prog_name="git-mirror")
def main() -> None:
    """git-mirror — mirror Git repositories with full ref fidelity."""


# ---------------------------------------------------------------------------
# Shared option decorators
# ---------------------------------------------------------------------------

_config_option = click.option(
    "-c", "--config", "config_path", required=True, help="Path to JSON config file."
)
_dry_run_option = click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print actions without executing.",
)
_parallel_option = click.option(
    "--parallel",
    default=None,
    type=int,
    help="Number of parallel workers (overrides config).",
)
_timeout_option = click.option(
    "--timeout",
    default=None,
    type=int,
    help="Per-repo timeout in seconds (overrides config).",
)
_verbose_option = click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)


# ---------------------------------------------------------------------------
# sync-all
# ---------------------------------------------------------------------------


@main.command("sync-all")
@_config_option
@_dry_run_option
@_parallel_option
@_timeout_option
@_verbose_option
def sync_all(
    config_path: str,
    dry_run: bool,
    parallel: int | None,
    timeout: int | None,
    verbose: bool,
) -> None:
    """Import and export all repositories defined in config."""
    _setup_logging(verbose)
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    workers = parallel or cfg.global_config.parallel
    secs = timeout or cfg.global_config.timeout
    results = run_parallel(
        sync_repo,
        cfg.repos,
        cfg.global_config.mirrors_dir,
        workers=workers,
        timeout=secs,
        dry_run=dry_run,
    )
    print_summary(results)
    if any(not r.success for r in results):
        sys.exit(1)


# ---------------------------------------------------------------------------
# import-all
# ---------------------------------------------------------------------------


@main.command("import-all")
@_config_option
@_dry_run_option
@_parallel_option
@_timeout_option
@_verbose_option
def import_all(
    config_path: str,
    dry_run: bool,
    parallel: int | None,
    timeout: int | None,
    verbose: bool,
) -> None:
    """Clone or fetch all source repos into local mirrors."""
    _setup_logging(verbose)
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    workers = parallel or cfg.global_config.parallel
    secs = timeout or cfg.global_config.timeout
    results = run_parallel(
        import_repo,
        cfg.repos,
        cfg.global_config.mirrors_dir,
        workers=workers,
        timeout=secs,
        dry_run=dry_run,
    )
    print_summary(results)
    if any(not r.success for r in results):
        sys.exit(1)


# ---------------------------------------------------------------------------
# export-all
# ---------------------------------------------------------------------------


@main.command("export-all")
@_config_option
@_dry_run_option
@_parallel_option
@_timeout_option
@_verbose_option
def export_all(
    config_path: str,
    dry_run: bool,
    parallel: int | None,
    timeout: int | None,
    verbose: bool,
) -> None:
    """Push all local mirrors to their destinations."""
    _setup_logging(verbose)
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    workers = parallel or cfg.global_config.parallel
    secs = timeout or cfg.global_config.timeout
    results = run_parallel(
        export_repo,
        cfg.repos,
        cfg.global_config.mirrors_dir,
        workers=workers,
        timeout=secs,
        dry_run=dry_run,
    )
    print_summary(results)
    if any(not r.success for r in results):
        sys.exit(1)


# ---------------------------------------------------------------------------
# sync (ad-hoc, no config file required)
# ---------------------------------------------------------------------------


@main.command("sync")
@click.option("--source", required=True, help="Source Git URL.")
@click.option("--dest", required=True, help="Destination Git URL.")
@click.option(
    "--name",
    default="adhoc",
    show_default=True,
    help="Name for the local mirror directory.",
)
@click.option("--lfs", is_flag=True, default=False, help="Mirror LFS objects.")
@click.option(
    "--mirrors-dir",
    default="~/.git-mirror/mirrors",
    show_default=True,
    help="Base directory for local mirror storage.",
)
@_dry_run_option
@_timeout_option
@_verbose_option
def sync_single(
    source: str,
    dest: str,
    name: str,
    lfs: bool,
    mirrors_dir: str,
    dry_run: bool,
    timeout: int | None,
    verbose: bool,
) -> None:
    """Mirror a single repo ad-hoc (no config file needed)."""
    _setup_logging(verbose)
    mirrors_dir = os.path.expandvars(os.path.expanduser(mirrors_dir))
    secs = timeout or 300
    repo = RepoConfig(name=name, source=source, dest=dest, lfs=lfs)
    result = sync_repo(repo, mirrors_dir, timeout=secs, dry_run=dry_run)
    if result.success:
        click.echo(f"Success: {result.message}")
    else:
        click.echo(f"Failed: {result.message}", err=True)
        sys.exit(1)
