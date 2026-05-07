"""
Click-based command-line interface for gitbit.

This module defines all user-facing subcommands and wires them to the sync
and config layers. It is the outermost layer of the application — it handles
user input, sets up logging, and translates library results into exit codes.

Command overview
----------------
  sync-all    Full pipeline: fetch all sources, push to all destinations.
  import-all  Fetch sources only (no push). Stage mirrors for later export.
  export-all  Push mirrors to destinations only (no fetch). Requires import first.
  sync        Ad-hoc single-repo mirror without a config file.
  validate    Check the config file offline — no network, no git calls.
  status      Show local mirror state (size, last-modified) — no network.

Architecture notes
------------------
  Shared option decorators (_config_option, _dry_run_option, etc.) are defined
  once as module-level Click option objects and applied via the decorator syntax
  (@_config_option) to avoid duplicating the same option definitions across the
  four batch commands.

  _setup_logging() is called at the start of every command so the log level
  and format are consistent regardless of which subcommand is invoked.

  All commands catch GitMirrorError from the config/sync layers and convert
  them to a user-readable message on stderr + sys.exit(1). Library code never
  calls sys.exit() directly.

  Exit codes:
    0 — all repos succeeded (or no errors found for validate).
    1 — one or more repos failed, config is invalid, or errors were found.
"""
from __future__ import annotations

import logging
import os
import sys
import time

import click

from . import __version__
from .config import RepoConfig, load_config, validate_config
from .exceptions import GitMirrorError
from .sync import export_repo, get_repo_status, import_repo, print_summary, run_parallel, sync_repo


# Shared Click context settings: support both -h and --help, and allow longer
# help text to avoid word-wrapping option descriptions too aggressively.
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"], max_content_width=100)


def _setup_logging(verbose: bool) -> None:
    """Configure the root logger for the current command invocation.

    Sets up a single StreamHandler to stderr with a timestamp + level prefix.
    DEBUG level is enabled when verbose=True (--verbose flag); INFO otherwise.
    Called at the start of every command before any library code runs.

    Args:
        verbose: When True, sets the log level to DEBUG to show every git
                 command, retry attempt, and internal state transition.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name="gitbit")
def main() -> None:
    """Gitbit — Mirror Git repositories with full ref fidelity.

    \b
    Clones every ref (branches, tags, notes) from a source and pushes them
    to a destination using git clone --mirror and git push --mirror.
    Supports SSH and HTTPS auth, Git LFS, parallel execution, and
    automatic retries with exponential backoff.

    Run 'gitbit COMMAND -h' for detailed help on any command.
    """


# ---------------------------------------------------------------------------
# Shared option decorators
#
# Defined once here and applied to each batch command via:
#   @main.command("name")
#   @_config_option
#   @_dry_run_option
#   ...
#
# This avoids repeating the same option definitions in four places and
# ensures that all batch commands have identical flag names and help text.
# ---------------------------------------------------------------------------

_config_option = click.option(
    "-c", "--config",
    "config_path",
    required=True,
    metavar="FILE",
    help="Path to the JSON configuration file.",
)
_dry_run_option = click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print each git command without executing it. No data is transferred.",
)
_parallel_option = click.option(
    "--parallel",
    default=None,
    type=int,
    metavar="N",
    help="Number of repositories to process concurrently. Overrides the config value.",
)
_timeout_option = click.option(
    "--timeout",
    default=None,
    type=int,
    metavar="SECONDS",
    help="Maximum time allowed per repository operation. Overrides the config value.",
)
_verbose_option = click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable DEBUG-level logging including every git command and retry attempt.",
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
    """Full sync: fetch all sources, then push to all destinations.

    \b
    For each repository defined in the config file:
      1. Clone the source (or fetch updates if already cloned).
      2. Optionally fetch all Git LFS objects.
      3. Push all refs to the destination using --mirror.

    Repositories are processed in parallel up to the --parallel limit.
    Failed repositories are reported in the summary but do not stop others.
    """
    _setup_logging(verbose)
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # CLI flags override config values when provided; fall back to config defaults.
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

    # Exit 1 if any repo failed so the caller (cron, CI, etc.) can detect errors.
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
    """Fetch all source repositories into local mirrors.

    \b
    For each repository in the config file, either:
      - Clones the source as a bare mirror (first run), or
      - Fetches and prunes updates into the existing mirror.

    Does NOT push to destinations. Use 'export-all' as a follow-up step,
    or use 'sync-all' to do both in one command.
    """
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
    """Push all local mirrors to their configured destinations.

    \b
    Pushes every ref from the local mirror to the destination using
    git push --mirror. Does NOT fetch from sources first.

    Requires local mirrors to exist — run 'import-all' beforehand,
    or use 'sync-all' to fetch and push in a single step.
    """
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
@click.option(
    "--source",
    required=True,
    metavar="URL",
    help="Source Git repository URL (SSH or HTTPS).",
)
@click.option(
    "--dest",
    required=True,
    metavar="URL",
    help="Destination Git repository URL (SSH or HTTPS).",
)
@click.option(
    "--name",
    default="adhoc",
    show_default=True,
    metavar="NAME",
    help="Label used for the local mirror directory (<name>.git).",
)
@click.option(
    "--lfs",
    is_flag=True,
    default=False,
    help="Also mirror Git LFS objects (requires git-lfs).",
)
@click.option(
    "--mirrors-dir",
    default="~/.gitbit/mirrors",
    show_default=True,
    metavar="PATH",
    help="Directory where local mirror clones are stored.",
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
    """Mirror a single repository from source to destination.

    \b
    No config file required. Clones the source as a bare mirror (or fetches
    updates if already cloned), then pushes all refs to the destination.
    Credentials are picked up from SSH agent or environment variables.
    """
    _setup_logging(verbose)

    # Expand ~ and $VAR in the mirrors-dir path since Click does not do this
    # automatically (unlike GlobalConfig's Pydantic validator).
    mirrors_dir = os.path.expandvars(os.path.expanduser(mirrors_dir))
    secs = timeout or 300

    # Build a minimal RepoConfig with no auth block — credentials come from
    # the ambient SSH agent or environment, which git uses by default.
    repo = RepoConfig(name=name, source=source, dest=dest, lfs=lfs)
    result = sync_repo(repo, mirrors_dir, timeout=secs, dry_run=dry_run)

    if result.success:
        click.echo(f"Success: {result.message}")
    else:
        click.echo(f"Failed: {result.message}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@main.command("validate")
@_config_option
@_verbose_option
def validate_cmd(config_path: str, verbose: bool) -> None:
    """Check the configuration file without making any network connections.

    \b
    Verifies:
      - Valid JSON syntax and schema
      - No duplicate repository names
      - HTTPS token environment variables are set and non-empty
      - SSH private key files exist on disk
      - mirrors_dir accessibility (warning if absent)

    Exits 0 if no errors are found (warnings do not affect the exit code).
    """
    _setup_logging(verbose)
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Collect all semantic issues; separate into errors and warnings for display.
    issues = validate_config(cfg)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    click.echo(f"Validating {config_path}")
    click.echo(
        f"  {len(cfg.repos)} repo(s) defined  |  "
        f"mirrors_dir: {cfg.global_config.mirrors_dir}"
    )
    click.echo()

    if not issues:
        click.echo("  All checks passed.")
    else:
        # Print every issue with a severity tag and the dotted field path so the
        # user knows exactly what to fix and where to find it in the config file.
        for issue in issues:
            tag = "[error]" if issue.severity == "error" else "[warn] "
            scope = f"{issue.repo} > {issue.field}" if issue.repo else issue.field
            click.echo(f"  {tag}  {scope}: {issue.message}")

    click.echo()
    click.echo(f"  {len(errors)} error(s), {len(warnings)} warning(s)")

    # Only errors cause a non-zero exit. Warnings are informational and should
    # not block automated pipelines that run validate as a pre-flight step.
    if errors:
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _format_age(ts: float) -> str:
    """Convert a Unix timestamp to a human-readable relative age string.

    Used in the status table to show when each mirror was last updated.
    Rounds down to the nearest whole unit for brevity.

    Args:
        ts: Unix timestamp (float) to measure age from now.

    Returns:
        A short string like '42s ago', '15m ago', '3h ago', or '2d ago'.
    """
    delta = int(time.time() - ts)
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


@main.command("status")
@_config_option
@_verbose_option
def status_cmd(config_path: str, verbose: bool) -> None:
    """Show local mirror status for all configured repositories.

    \b
    Displays for each repository:
      - Whether the local mirror directory exists
      - Total mirror size on disk
      - Time since the mirror was last modified

    No network connections are made.
    """
    _setup_logging(verbose)
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Collect status for every repo by walking their local mirror directories.
    statuses = [get_repo_status(r, cfg.global_config.mirrors_dir) for r in cfg.repos]
    present = sum(1 for s in statuses if s.present)

    click.echo(f"Mirror status  —  {config_path}")
    click.echo(f"Mirrors directory: {cfg.global_config.mirrors_dir}")
    click.echo()

    if not statuses:
        click.echo("  No repositories defined.")
        return

    # Compute column width dynamically based on the longest repo name so the
    # table stays aligned regardless of name length.
    name_w = max(len(s.name) for s in statuses) + 2

    click.echo(f"  {'NAME':<{name_w}}  {'MIRROR':<9}  {'SIZE':<11}  LAST MODIFIED")
    click.echo(f"  {'-' * name_w}  {'-' * 7}  {'-' * 9}  {'-' * 20}")

    for s in statuses:
        if s.present:
            size = f"{s.size_mb:.1f} MB"
            # last_modified is None only for empty directories; normally it is set.
            modified = _format_age(s.last_modified) if s.last_modified else "—"
            click.echo(f"  {s.name:<{name_w}}  {'present':<9}  {size:<11}  {modified}")
        else:
            click.echo(f"  {s.name:<{name_w}}  {'missing':<9}  {'—':<11}  —")

    click.echo()
    pending = len(statuses) - present
    click.echo(f"  {len(statuses)} repo(s)  —  {present} mirrored, {pending} pending")
