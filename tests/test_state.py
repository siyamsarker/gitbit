"""Tests for gitbit.state — load_state, save_state, record_results, get_failed_repos."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from gitbit.state import get_failed_repos, load_state, record_results, save_state
from gitbit.sync import RepoResult


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


class TestLoadState:
    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        result = load_state(tmp_path / "nonexistent.json")
        assert result == {"repos": {}}

    def test_returns_data_when_file_valid(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        data = {
            "repos": {
                "RepoA": {
                    "last_sync_at": "2026-05-08T10:30:00",
                    "last_sync_status": "success",
                    "last_error": None,
                    "last_command": "sync-all",
                }
            }
        }
        state_file.write_text(json.dumps(data), encoding="utf-8")
        result = load_state(state_file)
        assert result == data

    def test_returns_empty_when_json_not_a_dict(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = load_state(state_file)
        assert result == {"repos": {}}

    def test_returns_empty_when_no_repos_key(self, tmp_path: Path, caplog) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"other": "value"}), encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="gitbit.state"):
            result = load_state(state_file)
        assert result == {"repos": {}}
        assert "unexpected format" in caplog.text.lower()

    def test_returns_empty_on_json_decode_error(self, tmp_path: Path, caplog) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json!!!", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="gitbit.state"):
            result = load_state(state_file)
        assert result == {"repos": {}}
        assert "state file" in caplog.text.lower()

    def test_returns_empty_on_oserror(self, tmp_path: Path, caplog) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("{}", encoding="utf-8")
        with patch("gitbit.state.json.load", side_effect=OSError("permission denied")):
            with caplog.at_level(logging.WARNING, logger="gitbit.state"):
                result = load_state(state_file)
        assert result == {"repos": {}}
        assert "state file" in caplog.text.lower()


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------


class TestSaveState:
    def test_writes_correct_json(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state = {"repos": {"RepoA": {"last_sync_status": "success"}}}
        save_state(state, state_file)
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        assert loaded == state

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        state_file = tmp_path / "nested" / "dir" / "state.json"
        save_state({"repos": {}}, state_file)
        assert state_file.exists()

    def test_no_tmp_file_leftover(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        save_state({"repos": {}}, state_file)
        tmp_file = state_file.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_oserror_is_logged_not_raised(self, tmp_path: Path, caplog) -> None:
        state_file = tmp_path / "state.json"
        with patch("gitbit.state.json.dump", side_effect=OSError("disk full")):
            with caplog.at_level(logging.ERROR, logger="gitbit.state"):
                # Should NOT raise
                save_state({"repos": {}}, state_file)
        assert "failed to save" in caplog.text.lower()


# ---------------------------------------------------------------------------
# record_results
# ---------------------------------------------------------------------------


class TestRecordResults:
    def test_success_result_written_correctly(self) -> None:
        state: dict = {"repos": {}}
        result = RepoResult(name="RepoA", success=True, message="ok")
        record_results(state, [result], "sync-all")
        entry = state["repos"]["RepoA"]
        assert entry["last_sync_status"] == "success"
        assert entry["last_error"] is None
        assert entry["last_command"] == "sync-all"
        assert "last_sync_at" in entry

    def test_failure_result_stores_error_message(self) -> None:
        state: dict = {"repos": {}}
        result = RepoResult(name="RepoB", success=False, message="clone failed")
        record_results(state, [result], "import-all")
        entry = state["repos"]["RepoB"]
        assert entry["last_sync_status"] == "failed"
        assert entry["last_error"] == "clone failed"
        assert entry["last_command"] == "import-all"

    def test_overwrites_existing_entry(self) -> None:
        state: dict = {
            "repos": {
                "RepoA": {
                    "last_sync_at": "2026-01-01T00:00:00",
                    "last_sync_status": "failed",
                    "last_error": "old error",
                    "last_command": "sync-all",
                }
            }
        }
        result = RepoResult(name="RepoA", success=True, message="ok")
        record_results(state, [result], "sync-all")
        assert state["repos"]["RepoA"]["last_sync_status"] == "success"
        assert state["repos"]["RepoA"]["last_error"] is None

    def test_multiple_results_all_written(self) -> None:
        state: dict = {"repos": {}}
        results = [
            RepoResult(name="R1", success=True, message="ok"),
            RepoResult(name="R2", success=False, message="err"),
            RepoResult(name="R3", success=True, message="ok"),
        ]
        record_results(state, results, "export-all")
        assert len(state["repos"]) == 3
        assert state["repos"]["R1"]["last_sync_status"] == "success"
        assert state["repos"]["R2"]["last_sync_status"] == "failed"
        assert state["repos"]["R3"]["last_sync_status"] == "success"

    def test_empty_results_leaves_state_unchanged(self) -> None:
        state: dict = {"repos": {"existing": {"last_sync_status": "success"}}}
        record_results(state, [], "sync-all")
        assert list(state["repos"].keys()) == ["existing"]

    def test_sets_last_sync_at_timestamp(self) -> None:
        state: dict = {"repos": {}}
        result = RepoResult(name="R1", success=True, message="ok")
        record_results(state, [result], "sync-all")
        ts = state["repos"]["R1"]["last_sync_at"]
        # Should parse as ISO-8601 without error
        from datetime import datetime
        parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        assert parsed is not None


# ---------------------------------------------------------------------------
# get_failed_repos
# ---------------------------------------------------------------------------


class TestGetFailedRepos:
    def test_returns_failed_repo_names(self) -> None:
        state = {
            "repos": {
                "RepoA": {"last_sync_status": "success"},
                "RepoB": {"last_sync_status": "failed"},
                "RepoC": {"last_sync_status": "failed"},
            }
        }
        failed = get_failed_repos(state)
        assert failed == ["RepoB", "RepoC"]

    def test_returns_empty_when_no_failures(self) -> None:
        state = {
            "repos": {
                "RepoA": {"last_sync_status": "success"},
                "RepoB": {"last_sync_status": "success"},
            }
        }
        assert get_failed_repos(state) == []

    def test_skips_non_dict_entries(self) -> None:
        state = {
            "repos": {
                "RepoA": "not-a-dict",
                "RepoB": {"last_sync_status": "failed"},
            }
        }
        failed = get_failed_repos(state)
        assert failed == ["RepoB"]

    def test_empty_state_returns_empty_list(self) -> None:
        assert get_failed_repos({"repos": {}}) == []

    def test_preserves_insertion_order(self) -> None:
        state = {
            "repos": {
                "C": {"last_sync_status": "failed"},
                "A": {"last_sync_status": "failed"},
                "B": {"last_sync_status": "failed"},
            }
        }
        failed = get_failed_repos(state)
        assert failed == ["C", "A", "B"]
