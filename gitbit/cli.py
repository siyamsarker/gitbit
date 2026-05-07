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
  logs        View and filter the persistent activity log.

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
import re
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import click

from . import __version__
from .config import RepoConfig, load_config, validate_config
from .exceptions import GitMirrorError
from .state import STATE_FILE, get_failed_repos, load_state, record_results, save_state
from .sync import export_repo, get_repo_status, import_repo, print_summary, run_parallel, sync_repo


# Shared Click context settings: support both -h and --help, and allow longer
# help text to avoid word-wrapping option descriptions too aggressively.
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"], max_content_width=100)

# ---------------------------------------------------------------------------
# Persistent file logging
# ---------------------------------------------------------------------------

_LOG_DIR = Path.home() / ".gitbit" / "logs"
_LOG_FILE = _LOG_DIR / "gitbit.log"
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file before rotation
_LOG_BACKUP_COUNT = 5              # keep 5 rotated files → up to 30 MB total

# Parses a structured line written by the file log handler:
#   2026-05-08T10:30:00 INFO     sync-all     [Test Project] Cloning mirror...
_LOG_LINE_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'
    r'\s+(?P<level>[A-Z]+)'
    r'\s+(?P<command>\S+)'
    r'\s+(?P<message>.*)$'
)

_LEVEL_VALUES: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _CommandFilter(logging.Filter):
    """Inject the active command name into every log record for the file handler."""

    def __init__(self, command: str) -> None:
        super().__init__()
        self._command = command

    def filter(self, record: logging.LogRecord) -> bool:
        record.command = self._command  # type: ignore[attr-defined]
        return True


def _setup_logging(verbose: bool, command: str = "gitbit") -> None:
    """Configure root logger for the current command invocation.

    Sets up two handlers:
      - StreamHandler (stderr) for interactive terminal output.
      - RotatingFileHandler (~/.gitbit/logs/gitbit.log) for persistent audit log.

    The file handler includes the command name in every entry so logs from
    different commands can be filtered by source. Console output is unchanged.

    Args:
        verbose: When True, sets log level to DEBUG.
        command: Active CLI command name injected into every file log entry.
    """
    level = logging.DEBUG if verbose else logging.INFO

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(command)-12s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.filters.clear()
    root.addFilter(_CommandFilter(command))
    root.addHandler(console_handler)
    root.addHandler(file_handler)


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
_only_option = click.option(
    "--only",
    "only",
    multiple=True,
    metavar="NAME",
    help=(
        "Process ONLY the named repo(s). May be repeated. "
        "Mutually exclusive with --exclude and --retry-failed."
    ),
)
_exclude_option = click.option(
    "--exclude",
    "exclude",
    multiple=True,
    metavar="NAME",
    help=(
        "Skip the named repo(s). May be repeated. "
        "Mutually exclusive with --only and --retry-failed."
    ),
)
_fail_fast_option = click.option(
    "--fail-fast",
    "fail_fast",
    is_flag=True,
    default=False,
    help="Stop processing after the first repository failure.",
)
_retry_failed_option = click.option(
    "--retry-failed",
    "retry_failed",
    is_flag=True,
    default=False,
    help=(
        "Re-run only repos that failed in the previous run (from state file). "
        "Mutually exclusive with --only and --exclude."
    ),
)


def _format_sync_age(iso_str: str | None) -> str:
    """Convert an ISO-8601 timestamp from the state file to a relative age string.

    Parses the stored ``last_sync_at`` value and delegates to ``_format_age()``
    for the human-readable representation. Returns ``"never"`` when no timestamp
    has been recorded yet.

    Args:
        iso_str: An ISO-8601 datetime string like ``"2026-05-08T10:30:12"``,
                 or None if the repo has never been synced.

    Returns:
        A short relative age string (e.g. ``"2h ago"``) or ``"never"``.
    """
    if not iso_str:
        return "never"
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
        return _format_age(dt.timestamp())
    except ValueError:
        return "?"


def _select_repos(
    repos: list[RepoConfig],
    only: tuple[str, ...],
    exclude: tuple[str, ...],
    retry_failed: bool,
    state: dict,
) -> list[RepoConfig] | None:
    """Filter the repo list according to --only, --exclude, and --retry-failed.

    Validates mutual exclusivity of the flags and that named repos exist in the
    config. Emits warnings for --exclude names that are not in the config (they
    may be typos but are non-fatal). Emits errors and returns None for --only
    names that are not in the config (those are always mistakes).

    Args:
        repos:        Full list of RepoConfig objects from the loaded config.
        only:         Tuple of repo names from --only (may be empty).
        exclude:      Tuple of repo names from --exclude (may be empty).
        retry_failed: Whether --retry-failed was set.
        state:        State dict from load_state().

    Returns:
        The filtered list of RepoConfig objects, or None if a validation error
        was detected (the caller should then exit with code 1).
    """
    # --- Mutual exclusivity checks ---
    flags_set = [bool(only), bool(exclude), retry_failed]
    active = sum(flags_set)
    if active > 1:
        combos = []
        if only:
            combos.append("--only")
        if exclude:
            combos.append("--exclude")
        if retry_failed:
            combos.append("--retry-failed")
        click.echo(
            f"Error: {' and '.join(combos)} are mutually exclusive. "
            "Use at most one.",
            err=True,
        )
        return None

    name_to_repo = {r.name: r for r in repos}

    # --- --only: keep only the explicitly named repos ---
    if only:
        missing = [n for n in only if n not in name_to_repo]
        if missing:
            for m in missing:
                click.echo(f"Error: --only '{m}' is not defined in the config.", err=True)
            return None
        return [name_to_repo[n] for n in only if n in name_to_repo]

    # --- --exclude: remove the named repos ---
    if exclude:
        unknown = [n for n in exclude if n not in name_to_repo]
        for u in unknown:
            click.echo(f"Warning: --exclude '{u}' is not in config — skipping.", err=True)
        return [r for r in repos if r.name not in set(exclude)]

    # --- --retry-failed: keep only repos that failed last time ---
    if retry_failed:
        failed_names = get_failed_repos(state)
        if not failed_names:
            click.echo("No failed repos recorded in state. Nothing to retry.")
            return []  # Empty list — caller should exit 0
        # Warn about names in state that are no longer in config.
        for name in failed_names:
            if name not in name_to_repo:
                click.echo(
                    f"Warning: failed repo '{name}' is no longer in config — skipping.",
                    err=True,
                )
        selected = [name_to_repo[n] for n in failed_names if n in name_to_repo]
        if not selected:
            click.echo("No matching repos left after filtering. Nothing to retry.")
            return []
        return selected

    # --- No filter flags: process all repos ---
    return repos


# ---------------------------------------------------------------------------
# sync-all
# ---------------------------------------------------------------------------


@main.command("sync-all")
@_config_option
@_dry_run_option
@_parallel_option
@_timeout_option
@_verbose_option
@_only_option
@_exclude_option
@_fail_fast_option
@_retry_failed_option
def sync_all(
    config_path: str,
    dry_run: bool,
    parallel: int | None,
    timeout: int | None,
    verbose: bool,
    only: tuple[str, ...],
    exclude: tuple[str, ...],
    fail_fast: bool,
    retry_failed: bool,
) -> None:
    """Full sync: fetch all sources, then push to all destinations.

    \b
    For each repository defined in the config file:
      1. Clone the source (or fetch updates if already cloned).
      2. Optionally fetch all Git LFS objects.
      3. Push all refs to the destination using --mirror.

    Repositories are processed in parallel up to the --parallel limit.
    Failed repositories are reported in the summary but do not stop others
    unless --fail-fast is set.
    """
    _setup_logging(verbose, "sync-all")
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    state = load_state()
    selected = _select_repos(cfg.repos, only, exclude, retry_failed, state)
    if selected is None:
        sys.exit(1)
    if not selected:
        sys.exit(0)

    # CLI flags override config values when provided; fall back to config defaults.
    workers = parallel or cfg.global_config.parallel
    secs = timeout or cfg.global_config.timeout

    results = run_parallel(
        sync_repo,
        selected,
        cfg.global_config.mirrors_dir,
        workers=workers,
        timeout=secs,
        dry_run=dry_run,
        fail_fast=fail_fast,
    )
    print_summary(results)
    record_results(state, results, "sync-all")
    save_state(state)

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
@_only_option
@_exclude_option
@_fail_fast_option
@_retry_failed_option
def import_all(
    config_path: str,
    dry_run: bool,
    parallel: int | None,
    timeout: int | None,
    verbose: bool,
    only: tuple[str, ...],
    exclude: tuple[str, ...],
    fail_fast: bool,
    retry_failed: bool,
) -> None:
    """Fetch all source repositories into local mirrors.

    \b
    For each repository in the config file, either:
      - Clones the source as a bare mirror (first run), or
      - Fetches and prunes updates into the existing mirror.

    Does NOT push to destinations. Use 'export-all' as a follow-up step,
    or use 'sync-all' to do both in one command.
    """
    _setup_logging(verbose, "import-all")
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    state = load_state()
    selected = _select_repos(cfg.repos, only, exclude, retry_failed, state)
    if selected is None:
        sys.exit(1)
    if not selected:
        sys.exit(0)

    workers = parallel or cfg.global_config.parallel
    secs = timeout or cfg.global_config.timeout

    results = run_parallel(
        import_repo,
        selected,
        cfg.global_config.mirrors_dir,
        workers=workers,
        timeout=secs,
        dry_run=dry_run,
        fail_fast=fail_fast,
    )
    print_summary(results)
    record_results(state, results, "import-all")
    save_state(state)

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
@_only_option
@_exclude_option
@_fail_fast_option
@_retry_failed_option
def export_all(
    config_path: str,
    dry_run: bool,
    parallel: int | None,
    timeout: int | None,
    verbose: bool,
    only: tuple[str, ...],
    exclude: tuple[str, ...],
    fail_fast: bool,
    retry_failed: bool,
) -> None:
    """Push all local mirrors to their configured destinations.

    \b
    Pushes every ref from the local mirror to the destination using
    git push --mirror. Does NOT fetch from sources first.

    Requires local mirrors to exist — run 'import-all' beforehand,
    or use 'sync-all' to fetch and push in a single step.
    """
    _setup_logging(verbose, "export-all")
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    state = load_state()
    selected = _select_repos(cfg.repos, only, exclude, retry_failed, state)
    if selected is None:
        sys.exit(1)
    if not selected:
        sys.exit(0)

    workers = parallel or cfg.global_config.parallel
    secs = timeout or cfg.global_config.timeout

    results = run_parallel(
        export_repo,
        selected,
        cfg.global_config.mirrors_dir,
        workers=workers,
        timeout=secs,
        dry_run=dry_run,
        fail_fast=fail_fast,
    )
    print_summary(results)
    record_results(state, results, "export-all")
    save_state(state)

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
    _setup_logging(verbose, "sync")

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
    _setup_logging(verbose, "validate")
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
      - Time since the last successful or failed sync (from state file)
      - Last sync status: success, failed, or — (never synced)

    No network connections are made.
    """
    _setup_logging(verbose, "status")
    try:
        cfg = load_config(config_path)
    except GitMirrorError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Load persistent sync state to populate LAST SYNC / STATUS columns.
    state = load_state()
    repo_state = state.get("repos", {})

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

    click.echo(
        f"  {'NAME':<{name_w}}  {'MIRROR':<9}  {'SIZE':<11}  {'LAST MODIFIED':<22}  {'LAST SYNC':<12}  STATUS"
    )
    click.echo(
        f"  {'-' * name_w}  {'-' * 7}  {'-' * 9}  {'-' * 20}  {'-' * 10}  {'-' * 7}"
    )

    for s in statuses:
        # Pull sync metadata from the state file (may be absent for unseen repos).
        entry = repo_state.get(s.name, {})
        last_sync = _format_sync_age(entry.get("last_sync_at"))
        sync_status = entry.get("last_sync_status", "—") if entry else "—"

        if s.present:
            size = f"{s.size_mb:.1f} MB"
            # last_modified is None only for empty directories; normally it is set.
            modified = _format_age(s.last_modified) if s.last_modified else "—"
            click.echo(
                f"  {s.name:<{name_w}}  {'present':<9}  {size:<11}  {modified:<22}  {last_sync:<12}  {sync_status}"
            )
        else:
            click.echo(
                f"  {s.name:<{name_w}}  {'missing':<9}  {'—':<11}  {'—':<22}  {last_sync:<12}  {sync_status}"
            )

    click.echo()
    pending = len(statuses) - present
    click.echo(f"  {len(statuses)} repo(s)  —  {present} mirrored, {pending} pending")


# ---------------------------------------------------------------------------
# Log viewer helpers
# ---------------------------------------------------------------------------


def _log_files() -> list[Path]:
    """Return all gitbit log files ordered from oldest to newest."""
    files: list[Path] = []
    for i in range(_LOG_BACKUP_COUNT, 0, -1):
        p = _LOG_FILE.parent / f"{_LOG_FILE.name}.{i}"
        if p.exists():
            files.append(p)
    if _LOG_FILE.exists():
        files.append(_LOG_FILE)
    return files


def _parse_since(value: str) -> datetime:
    """Parse a --since expression into an absolute datetime cutoff.

    Accepts relative durations (30m, 2h, 7d) and absolute timestamps
    (2026-05-08, 2026-05-08T10:30:00).
    """
    m = re.fullmatch(r'(\d+)([hmd])', value.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {'h': timedelta(hours=n), 'm': timedelta(minutes=n), 'd': timedelta(days=n)}[unit]
        return datetime.now() - delta
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse '{value}'. "
        "Use: 30m, 2h, 7d, 2026-05-08, or 2026-05-08T10:30:00"
    )


def _read_log_lines(since_dt: datetime | None) -> list[str]:
    """Read log lines from all log files, optionally skipping entries before since_dt."""
    lines: list[str] = []
    for log_file in _log_files():
        try:
            with log_file.open(encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.rstrip("\n")
                    if not line:
                        continue
                    if since_dt is not None:
                        match = _LOG_LINE_RE.match(line)
                        if match:
                            try:
                                ts = datetime.strptime(match.group("ts"), "%Y-%m-%dT%H:%M:%S")
                                if ts < since_dt:
                                    continue
                            except ValueError:
                                pass
                    lines.append(line)
        except OSError:
            pass
    return lines


def _matches_filters(
    line: str,
    min_level_int: int,
    cmd_filter: str | None,
    repo_filter: str | None,
) -> bool:
    """Return True if the log line passes all active filters."""
    match = _LOG_LINE_RE.match(line)
    if not match:
        return False
    if _LEVEL_VALUES.get(match.group("level").upper(), 0) < min_level_int:
        return False
    if cmd_filter and match.group("command").lower() != cmd_filter.lower():
        return False
    if repo_filter and f"[{repo_filter}]" not in match.group("message"):
        return False
    return True


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


@main.command("logs")
@click.option(
    "-n", "--tail",
    default=100,
    type=int,
    metavar="N",
    show_default=True,
    help="Show the last N entries. Use 0 to show all entries.",
)
@click.option(
    "--level",
    "min_level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="Show only entries at or above this log level.",
)
@click.option(
    "--command",
    "cmd_filter",
    type=click.Choice(
        ["sync-all", "import-all", "export-all", "sync", "validate", "status"],
        case_sensitive=False,
    ),
    default=None,
    help="Show only entries produced by this command.",
)
@click.option(
    "--repo",
    "repo_filter",
    default=None,
    metavar="NAME",
    help="Show only entries that mention this repository name.",
)
@click.option(
    "--since",
    "since_str",
    default=None,
    metavar="EXPR",
    help=(
        "Show entries from this point forward. "
        "Accepts: 30m, 2h, 7d, 2026-05-08, 2026-05-08T10:30:00"
    ),
)
@click.option(
    "-f", "--follow",
    is_flag=True,
    default=False,
    help="Stream new log entries as they are written (Ctrl-C to stop).",
)
def logs_cmd(
    tail: int,
    min_level: str | None,
    cmd_filter: str | None,
    repo_filter: str | None,
    since_str: str | None,
    follow: bool,
) -> None:
    """View and filter the persistent gitbit activity log.

    \b
    Reads ~/.gitbit/logs/gitbit.log and all rotated backups.
    Every sync, validate, and status run is recorded there automatically.

    \b
    Examples:
      gitbit logs                                    Last 100 entries
      gitbit logs -n 50                              Last 50 entries
      gitbit logs --level ERROR                      Errors only
      gitbit logs --level WARNING                    Warnings and errors
      gitbit logs --command sync-all                 sync-all activity only
      gitbit logs --repo "Test Project"              One repo's activity
      gitbit logs --since 1h                         Last hour
      gitbit logs --since 2026-05-08                 From a specific date
      gitbit logs --command sync-all --level ERROR   Errors from sync-all
      gitbit logs -f                                 Follow live (Ctrl-C to stop)
    """
    if not _log_files():
        click.echo("No log file found. Run a gitbit command first to generate logs.")
        return

    since_dt: datetime | None = None
    if since_str:
        try:
            since_dt = _parse_since(since_str)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    min_level_int = _LEVEL_VALUES.get((min_level or "").upper(), 0)

    def passes(line: str) -> bool:
        return _matches_filters(line, min_level_int, cmd_filter, repo_filter)

    if follow:
        for line in _read_log_lines(since_dt):
            if passes(line):
                click.echo(line)
        # Tail the live log file for new entries.
        try:
            with _LOG_FILE.open(encoding="utf-8", errors="replace") as fh:
                fh.seek(0, 2)  # jump to end of file
                while True:
                    raw = fh.readline()
                    if raw:
                        line = raw.rstrip("\n")
                        if passes(line):
                            click.echo(line)
                            sys.stdout.flush()
                    else:
                        time.sleep(0.3)
        except KeyboardInterrupt:
            pass
        return

    filtered = [ln for ln in _read_log_lines(since_dt) if passes(ln)]

    if tail > 0:
        filtered = filtered[-tail:]

    if not filtered:
        click.echo("No log entries match the given filters.")
        return

    for line in filtered:
        click.echo(line)
