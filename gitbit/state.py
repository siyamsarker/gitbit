"""
Persistent sync state for gitbit.

This module manages a JSON state file that records the outcome of every
sync/import/export operation. The state file is stored at:

    ~/.gitbit/state.json

It is read before each batch command to support --retry-failed (which re-runs
only repos that failed last time), and written after each batch command to
capture the latest result for every processed repo.

State file format
-----------------
{
  "repos": {
    "ProjectA": {
      "last_sync_at": "2026-05-08T10:30:12",
      "last_sync_status": "success",
      "last_error": null,
      "last_command": "sync-all"
    },
    "RepoB": {
      "last_sync_at": "2026-05-08T10:31:05",
      "last_sync_status": "failed",
      "last_error": "Connection timed out after 300s",
      "last_command": "sync-all"
    }
  }
}

Atomic writes
-------------
save_state() writes to a .tmp file first, then renames it over the real file.
This guarantees that a crash mid-write never leaves a corrupt state file — the
rename is atomic on POSIX systems.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sync import RepoResult

logger = logging.getLogger(__name__)

# Default location for the persistent state file.
STATE_FILE = Path.home() / ".gitbit" / "state.json"


def load_state(path: Path = STATE_FILE) -> dict:
    """Load the gitbit state file from disk.

    Returns an empty state skeleton if the file does not exist or its
    contents cannot be parsed as valid JSON. This makes the function safe
    to call on a fresh system where no state has been recorded yet.

    Args:
        path: Filesystem path to the state JSON file. Defaults to STATE_FILE.

    Returns:
        A dict with at least a ``"repos"`` key mapping repo names to their
        last-sync metadata. If the file is absent or corrupt, returns
        ``{"repos": {}}``.
    """
    empty: dict = {"repos": {}}
    if not path.exists():
        return empty
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        # Guard against a file that is valid JSON but has the wrong shape.
        if not isinstance(data, dict) or "repos" not in data:
            logger.warning("State file at %s has unexpected format; resetting.", path)
            return empty
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read state file %s (%s); starting fresh.", path, exc)
        return empty


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    """Atomically write the state dict to disk.

    Writes to a sibling ``.tmp`` file first, then renames it over the real
    file. The rename is atomic on POSIX systems, so a crash during the write
    can never leave the state file in a partially written (corrupt) state.

    The parent directory is created automatically if it does not yet exist.

    Args:
        state: The state dict to serialise. Must be JSON-serialisable.
        path:  Destination path. Defaults to STATE_FILE.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        tmp.rename(path)
    except OSError as exc:
        logger.error("Failed to save state file %s: %s", path, exc)


def record_results(state: dict, results: list["RepoResult"], command: str) -> None:
    """Update the state dict in-place with the results of the latest batch run.

    For each RepoResult in ``results``, writes (or overwrites) the entry for
    that repo under ``state["repos"]``. The timestamp is set to the current
    local time in ISO-8601 format (seconds precision, no timezone suffix).

    This function mutates ``state`` directly; call ``save_state()`` afterwards
    to persist the changes to disk.

    Args:
        state:   The state dict as returned by ``load_state()``. Modified in-place.
        results: List of RepoResult objects from ``run_parallel()`` or a direct
                 sync/import/export call.
        command: The CLI command name that produced these results
                 (e.g. ``"sync-all"``). Stored verbatim in the state entry.
    """
    repos = state.setdefault("repos", {})
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for result in results:
        repos[result.name] = {
            "last_sync_at": now,
            "last_sync_status": "success" if result.success else "failed",
            "last_error": None if result.success else result.message,
            "last_command": command,
        }


def get_failed_repos(state: dict) -> list[str]:
    """Return the names of all repos whose last sync ended in failure.

    Reads ``state["repos"]`` and collects every repo name where
    ``last_sync_status == "failed"``. The order of the returned list matches
    the order the keys appear in the state dict (insertion order in Python 3.7+).

    Args:
        state: The state dict as returned by ``load_state()``.

    Returns:
        A list of repo name strings. Returns an empty list if no repos have
        a recorded failure or if the state has no entries at all.
    """
    return [
        name
        for name, info in state.get("repos", {}).items()
        if isinstance(info, dict) and info.get("last_sync_status") == "failed"
    ]
