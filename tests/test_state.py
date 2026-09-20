import json
from datetime import timedelta
from pathlib import Path

from factories import NOW

from state import SeenState


def test_missing_file_loads_as_empty_and_not_existing(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    assert not state.existed
    assert len(state) == 0


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "data" / "seen.json"
    state = SeenState.load(path)
    state.add("42", NOW)
    state.save()

    reloaded = SeenState.load(path)
    assert reloaded.existed
    assert "42" in reloaded
    assert "43" not in reloaded


def test_add_keeps_the_first_seen_time(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("42", NOW)
    state.add("42", NOW + timedelta(days=1))
    state.save()

    saved = json.loads((tmp_path / "seen.json").read_text())
    assert saved["seen"]["42"] == NOW.isoformat(timespec="seconds")


def test_prune_drops_only_old_entries(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("old", NOW - timedelta(days=40))
    state.add("recent", NOW - timedelta(days=5))
    state.prune(NOW, keep_days=30)

    assert "old" not in state
    assert "recent" in state


def test_saved_file_is_sorted_for_stable_diffs(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("9", NOW)
    state.add("10", NOW)
    state.save()

    saved = json.loads((tmp_path / "seen.json").read_text())
    assert list(saved["seen"]) == ["10", "9"]
