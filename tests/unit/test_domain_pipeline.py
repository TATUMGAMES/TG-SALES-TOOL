from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tg_sales.domain.pipeline import (
    EventCorrection,
    StageEvent,
    apply_corrections,
    stage_counts,
    stages_as_of,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def at(days: float) -> datetime:
    return T0 + timedelta(days=days)


def event(
    event_id: str, opp: str, stage: str, occurred: float, recorded: float | None = None
) -> StageEvent:
    return StageEvent(event_id, opp, stage, at(occurred), at(recorded if recorded else occurred))


EVENTS = [
    event("e1", "A", "discovered", 0),
    event("e2", "A", "contacted", 5),
    event("e3", "A", "won", 10),
    event("e4", "B", "discovered", 3),
    event("e5", "B", "contacted", 8),
]


def test_stage_as_of_uses_history_not_current_state() -> None:
    assert stages_as_of(EVENTS, at(-1)) == {}
    assert stages_as_of(EVENTS, at(0)) == {"A": "discovered"}  # inclusive boundary
    assert stages_as_of(EVENTS, at(4)) == {"A": "discovered", "B": "discovered"}
    assert stages_as_of(EVENTS, at(9)) == {"A": "contacted", "B": "contacted"}
    assert stages_as_of(EVENTS, at(30)) == {"A": "won", "B": "contacted"}


def test_order_of_input_does_not_matter() -> None:
    assert stages_as_of(list(reversed(EVENTS)), at(9)) == stages_as_of(EVENTS, at(9))


def test_ties_break_by_recorded_time_then_event_id() -> None:
    tied = [
        event("x2", "A", "late-recorded", 1, recorded=3),
        event("x1", "A", "early-recorded", 1, recorded=2),
    ]
    assert stages_as_of(tied, at(1)) == {"A": "late-recorded"}
    same_moment = [event("b", "A", "second", 1), event("a", "A", "first", 1)]
    assert stages_as_of(same_moment, at(1)) == {"A": "second"}


def test_backdated_events_are_placed_by_occurrence_time() -> None:
    events = [*EVENTS, event("late", "B", "interested", 6, recorded=20)]
    assert stages_as_of(events, at(7)) == {"A": "contacted", "B": "interested"}
    assert stages_as_of(events, at(9))["B"] == "contacted"


def test_void_correction_removes_event() -> None:
    corrections = [EventCorrection("c1", "e3", at(12), void=True)]
    corrected = apply_corrections(EVENTS, corrections)
    assert stages_as_of(corrected, at(30))["A"] == "contacted"


def test_retime_correction_moves_event_and_latest_correction_wins() -> None:
    corrections = [
        EventCorrection("c1", "e3", at(11), occurred_at=at(2)),
        EventCorrection("c2", "e3", at(12), occurred_at=at(7)),
    ]
    corrected = apply_corrections(EVENTS, corrections)
    assert stages_as_of(corrected, at(6))["A"] == "contacted"
    assert stages_as_of(corrected, at(7))["A"] == "won"


def test_correction_without_change_keeps_event() -> None:
    corrected = apply_corrections(EVENTS, [EventCorrection("c", "e1", at(1))])
    assert corrected == EVENTS


def test_stage_counts() -> None:
    assert stage_counts(stages_as_of(EVENTS, at(9))) == {"contacted": 2}
