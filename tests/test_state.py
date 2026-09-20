import json
from datetime import timedelta
from pathlib import Path

from factories import NOW

from state import SeenState


def test_missing_file_loads_as_empty_and_not_baselined(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    assert not state.baselined
    assert state.last_full_sweep is None
    assert len(state) == 0


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "data" / "seen.json"
    state = SeenState.load(path)
    state.add("42", NOW)
    state.mark_baselined()
    state.mark_full_sweep(NOW)
    state.save()

    reloaded = SeenState.load(path)
    assert "42" in reloaded
    assert "43" not in reloaded
    assert reloaded.baselined
    assert reloaded.last_full_sweep == NOW


def test_state_file_from_before_baselining_counts_as_not_baselined(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({"seen": {"1": NOW.isoformat()}}))

    state = SeenState.load(path)
    assert "1" in state
    assert not state.baselined


def test_touch_refreshes_only_stale_entries(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("stale", NOW - timedelta(days=10))
    state.add("fresh", NOW - timedelta(days=2))
    state.touch("stale", NOW)
    state.touch("fresh", NOW)
    state.save()

    saved = json.loads((tmp_path / "seen.json").read_text())["seen"]
    assert saved["stale"] == NOW.isoformat(timespec="seconds")
    assert saved["fresh"] == (NOW - timedelta(days=2)).isoformat(timespec="seconds")


def test_touch_ignores_unknown_ids(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.touch("nope", NOW)
    assert "nope" not in state


def test_prune_drops_only_entries_unseen_for_too_long(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("gone", NOW - timedelta(days=40))
    state.add("kept", NOW - timedelta(days=5))
    state.prune(NOW, keep_days=30)

    assert "gone" not in state
    assert "kept" in state


def test_a_touched_listing_survives_pruning(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("long-running", NOW - timedelta(days=60))
    state.touch("long-running", NOW)
    state.prune(NOW, keep_days=30)

    assert "long-running" in state


def test_full_sweep_due(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    assert state.full_sweep_due(NOW, every_hours=12)

    state.mark_full_sweep(NOW - timedelta(hours=11))
    assert not state.full_sweep_due(NOW, every_hours=12)

    state.mark_full_sweep(NOW - timedelta(hours=12))
    assert state.full_sweep_due(NOW, every_hours=12)


def test_saved_file_is_sorted_for_stable_diffs(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "seen.json")
    state.add("9", NOW)
    state.add("10", NOW)
    state.save()

    saved = json.loads((tmp_path / "seen.json").read_text())
    assert list(saved["seen"]) == ["10", "9"]
