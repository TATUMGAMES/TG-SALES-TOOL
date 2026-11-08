"""Technical handoff drafts for data-licensing opportunities.

A handoff summarizes what a prospective data buyer needs so the technical lead
can assess it. tg_sales only drafts the text for the salesperson to copy into
their own email client; it never sends anything, and the draft states that no
dataset is approved for sale until an authorized review has taken place.
"""

from __future__ import annotations

from dataclasses import dataclass

REVIEW_NOTICE = (
    "Nothing in this summary approves any dataset for sale or commits Tatum Games to "
    "delivering specific data. Availability, scope, pricing and terms require an "
    "authorized internal review before anything is offered to the prospect."
)

NOT_PROVIDED = "Not provided yet"


@dataclass(frozen=True)
class HandoffDraft:
    recipient: str
    organization: str
    website: str | None
    contact: str | None
    opportunity: str
    proposed_dataset: str = ""
    use_case: str = ""
    fields_and_format: str = ""
    refresh_cadence: str = ""
    privacy_security: str = ""
    delivery_expectations: str = ""
    open_questions: str = ""
    prepared_by: str | None = None


def handoff_subject(draft: HandoffDraft) -> str:
    return f"Technical handoff: {draft.organization} — data licensing ({draft.opportunity})"


def _section(title: str, text: str) -> str:
    body = text.strip() or NOT_PROVIDED
    return f"{title}\n{body}\n"


def render_handoff(draft: HandoffDraft) -> str:
    """Plain-text email body (with To and Subject lines) ready to copy."""
    lines = [f"To: {draft.recipient}"] if draft.recipient.strip() else []
    lines += [
        f"Subject: {handoff_subject(draft)}",
        "",
        "Hello,",
        "",
        "Please review this data-licensing lead and let me know what we can discuss.",
        "",
        _section(
            "Organization", draft.organization + (f" ({draft.website})" if draft.website else "")
        ),
        _section("Contact", draft.contact or ""),
        _section("Opportunity", draft.opportunity),
        _section("Proposed dataset", draft.proposed_dataset),
        _section("Intended use case", draft.use_case),
        _section("Fields and format", draft.fields_and_format),
        _section("Refresh cadence", draft.refresh_cadence),
        _section("Privacy and security requirements", draft.privacy_security),
        _section("Delivery expectations", draft.delivery_expectations),
        _section("Unresolved questions", draft.open_questions),
        f"Important: {REVIEW_NOTICE}",
        "",
        "Thanks,",
        draft.prepared_by or "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def missing_sections(draft: HandoffDraft) -> list[str]:
    """Names of the sections still empty (shown as a reminder, not a blocker)."""
    checks = (
        ("Proposed dataset", draft.proposed_dataset),
        ("Intended use case", draft.use_case),
        ("Fields and format", draft.fields_and_format),
        ("Refresh cadence", draft.refresh_cadence),
        ("Privacy and security requirements", draft.privacy_security),
        ("Delivery expectations", draft.delivery_expectations),
    )
    return [name for name, value in checks if not value.strip()]
