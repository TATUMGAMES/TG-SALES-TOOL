from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tg_sales.domain.enums import ActivityType, ContactStatus, ProductLane, StageOutcome
from tg_sales.domain.handoff import (
    NOT_PROVIDED,
    HandoffDraft,
    handoff_subject,
    missing_sections,
    render_handoff,
)
from tg_sales.domain.opportunities import (
    ACTIVITY_LABELS,
    LOGGABLE_ACTIVITIES,
    REASON_CODES,
    OpportunityCard,
    StageInfo,
    contact_status_after,
    reason_label,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("current", "activity", "expected"),
    [
        (ContactStatus.UNKNOWN, ActivityType.EMAIL, ContactStatus.ATTEMPTED),
        (ContactStatus.NOT_CONTACTED, ActivityType.LINKEDIN_INVITE, ContactStatus.ATTEMPTED),
        (ContactStatus.ATTEMPTED, ActivityType.REPLY, ContactStatus.RESPONDED),
        (ContactStatus.UNKNOWN, ActivityType.MEETING, ContactStatus.RESPONDED),
        (ContactStatus.RESPONDED, ActivityType.EMAIL, ContactStatus.RESPONDED),
        (ContactStatus.UNKNOWN, ActivityType.CLOSED, ContactStatus.UNKNOWN),
        (ContactStatus.UNKNOWN, ActivityType.TECHNICAL_HANDOFF, ContactStatus.UNKNOWN),
    ],
)
def test_contact_status_only_moves_forward(
    current: ContactStatus, activity: ActivityType, expected: ContactStatus
) -> None:
    assert contact_status_after(current, activity) is expected


def test_every_loggable_type_has_a_label_and_terminal_outcomes_have_reasons() -> None:
    assert all(kind in ACTIVITY_LABELS for kind, _ in LOGGABLE_ACTIVITIES)
    assert set(REASON_CODES) == {o for o in StageOutcome if o.is_terminal}
    for codes in REASON_CODES.values():
        assert "other" in {code for code, _ in codes}
    assert reason_label(StageOutcome.LOST, "price") == "Price or budget"
    assert reason_label(StageOutcome.LOST, "unknown_code") == "unknown_code"
    assert reason_label(StageOutcome.WON, None) is None


def test_stage_applies_to_lane() -> None:
    general = StageInfo("a", "A", 10, None, StageOutcome.OPEN, False)
    data_only = StageInfo("b", "B", 20, ProductLane.DATA_LICENSING, StageOutcome.OPEN, False)
    assert general.applies_to(ProductLane.MIKROS_MARKETING)
    assert data_only.applies_to(ProductLane.DATA_LICENSING)
    assert not data_only.applies_to(ProductLane.MIKROS_MARKETING)
    assert data_only.applies_to(None)


def card(next_action: datetime | None, closed: bool = False) -> OpportunityCard:
    return OpportunityCard(
        "o",
        "org",
        "Pixel Forge",
        "Data deal",
        ProductLane.DATA_LICENSING,
        "s",
        "Kim",
        NOW - timedelta(days=2),
        next_action,
        "Call back",
        date(2027, 3, 1),
        closed,
    )


def test_overdue_only_for_open_cards_with_past_next_action() -> None:
    assert card(NOW - timedelta(minutes=1)).overdue(NOW)
    assert not card(NOW + timedelta(minutes=1)).overdue(NOW)
    assert not card(None).overdue(NOW)
    assert not card(NOW - timedelta(days=1), closed=True).overdue(NOW)


def test_handoff_rendering() -> None:
    draft = HandoffDraft(
        recipient="lead@studio.example",
        organization="Pixel Forge",
        website="https://pixelforge.example",
        contact="Ana Ruiz <ana@pixelforge.example>",
        opportunity="Historical data",
        proposed_dataset="Daily session metrics",
        prepared_by="Kim",
    )
    text = render_handoff(draft)
    assert text.splitlines()[0] == "To: lead@studio.example"
    assert text.splitlines()[1] == f"Subject: {handoff_subject(draft)}"
    assert "Pixel Forge (https://pixelforge.example)" in text
    assert "Daily session metrics" in text
    assert text.count(NOT_PROVIDED) == 6
    assert "requires an authorized internal review" in text.replace("\n", " ") or (
        "authorized internal review" in text
    )
    assert text.rstrip().endswith("Kim")
    assert "Proposed dataset" not in missing_sections(draft)
    assert "Refresh cadence" in missing_sections(draft)
