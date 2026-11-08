"""Example outreach templates for Tatum Games, added only when the user asks.

Every example starts as *not approved*. Figures such as audience sizes are
claims supplied by the business and must be confirmed before external use;
incentives such as event invitations or fee waivers are selective and need
approval for each studio. The notes on each example say so.
"""

from __future__ import annotations

from dataclasses import dataclass

from tg_sales.domain.playbook import Channel, TemplateDraft

CLAIMS_NOTE = (
    "Figures in this message are business-supplied claims. Confirm they are current and "
    "approved before using the template externally."
)
INCENTIVE_NOTE = (
    "Event invitations and any vendor-fee waiver are selective and need approval for each "
    "studio. Never present them as guaranteed, and do not promise event access or "
    "distribution."
)
DATA_NOTE = (
    "Keep this high level. Do not make claims about data contents, sources, coverage or "
    "privacy compliance beyond what has been approved; route technical questions to the "
    "technical lead using the Technical handoff action."
)


@dataclass(frozen=True, slots=True)
class Example:
    key: str
    draft: TemplateDraft


EXAMPLES: tuple[Example, ...] = (
    Example(
        "data-buyer-intro-v1",
        TemplateDraft(
            title="Data buyer: dataset introduction",
            channel=Channel.DATA_BUYER,
            audience="Data buyer",
            category="Introduction",
            label="Intro",
            stage="Contacted",
            tags=("data", "intro"),
            body=(
                "Hi {contact_name},\n\n"
                "I lead partnerships at Tatum Games. We work with game industry data and "
                "wanted to briefly introduce a dataset that may be relevant to your team.\n\n"
                "If it is of interest, I can share a short overview of what it covers. For "
                "detailed technical questions, I will connect you with our technical lead.\n\n"
                "Would a 20-minute call in the next couple of weeks be useful?\n\n"
                "Best regards"
            ),
            notes=DATA_NOTE,
        ),
    ),
    Example(
        "data-buyer-technical-follow-up-v1",
        TemplateDraft(
            title="Data buyer: technical questions follow-up",
            channel=Channel.FOLLOW_UP,
            audience="Data buyer",
            category="Follow-up",
            stage="Replied",
            tags=("data", "handoff"),
            body=(
                "Hi {contact_name},\n\n"
                "Thank you for your questions. I have passed them to our technical lead, who "
                "is the right person to answer them accurately and will follow up with you "
                "directly.\n\n"
                "Best regards"
            ),
            notes=DATA_NOTE,
        ),
    ),
    Example(
        "publisher-mikros-marketing-v1",
        TemplateDraft(
            title="Publisher: MIKROS Marketing introduction",
            channel=Channel.PUBLISHER,
            audience="Publisher",
            category="Introduction",
            label="Intro",
            stage="Contacted",
            tags=("publisher", "MIKROS Marketing"),
            body=(
                "Hi {contact_name},\n\n"
                "I'm reaching out from Tatum Games. MIKROS Marketing is our platform-agnostic "
                "service for game discovery, analytics and community exposure, and it can "
                "support titles across your portfolio regardless of platform.\n\n"
                "We are also open to exploring a publishing collaboration with Tatum Tech "
                "where there is a good fit.\n\n"
                "Would you be open to a short call to see whether it is relevant for "
                "{studio_name}?\n\n"
                "Best regards"
            ),
            notes="Collaboration terms are not offered by default; discuss internally first.",
        ),
    ),
    Example(
        "studio-agency-support-v1",
        TemplateDraft(
            title="Game studio: launch support introduction",
            channel=Channel.EMAIL,
            audience="Game studio",
            category="Introduction",
            label="Intro",
            stage="Contacted",
            tags=("studio", "launch"),
            body=(
                "Hi {contact_name},\n\n"
                "Congratulations on {game_title}, coming to {platform} on {release_date}. "
                "I'm with Tatum Games, and we help studios like {studio_name} get noticed "
                "around launch:\n\n"
                "- writing and social media agency support\n"
                "- access to an influencer network of 3.2M+\n"
                "- exposure to the MIKROS Mafia community of 250K+ members\n"
                "- optional Tatum Tech app and event activations\n\n"
                "Would you be open to a short call to see what would help most?\n\n"
                "Best regards"
            ),
            notes=CLAIMS_NOTE,
        ),
    ),
    Example(
        "studio-linkedin-connect-v1",
        TemplateDraft(
            title="Game studio: LinkedIn connection note",
            channel=Channel.LINKEDIN_CONNECT,
            audience="Game studio",
            category="Introduction",
            label="Short",
            tags=("studio", "linkedin"),
            body=(
                "Hi {contact_name}, congratulations on {game_title}! I work with studios on "
                "launch marketing and community growth at Tatum Games. Would love to connect "
                "and follow {studio_name}'s journey."
            ),
            notes="Keep connection notes short; LinkedIn limits their length.",
        ),
    ),
    Example(
        "la-studio-event-v1",
        TemplateDraft(
            title="Los Angeles studio: event activation (approval needed)",
            channel=Channel.EMAIL,
            audience="Los Angeles studio",
            category="Event",
            label="Selective",
            stage="Contacted",
            tags=("studio", "Los Angeles", "event"),
            body=(
                "Hi {contact_name},\n\n"
                "Tatum Tech hosts invite-only event activations in Los Angeles, and we are "
                "considering a small number of local studios for upcoming events. Based on "
                "what we have seen of {game_title}, {studio_name} could be a good fit.\n\n"
                "Participation is by invitation and subject to approval; in some cases a "
                "vendor-fee waiver of up to $500 may be available. If you are interested, I "
                "can share more details.\n\n"
                "Best regards"
            ),
            notes=f"{INCENTIVE_NOTE} {CLAIMS_NOTE}",
        ),
    ),
    Example(
        "general-follow-up-v1",
        TemplateDraft(
            title="Follow-up after no reply",
            channel=Channel.FOLLOW_UP,
            audience="Game studio",
            category="Follow-up",
            stage="Contacted",
            tags=("follow-up",),
            body=(
                "Hi {contact_name},\n\n"
                "Just following up on my note about {game_title}. If launch support is not a "
                "priority right now, no problem at all; let me know and I won't follow up "
                "again.\n\n"
                "Best regards"
            ),
        ),
    ),
    Example(
        "phone-opening-v1",
        TemplateDraft(
            title="Phone call opening",
            channel=Channel.PHONE,
            audience="Game studio",
            category="Call script",
            tags=("phone",),
            body=(
                "Hi {contact_name}, I am calling from Tatum Games. Is now a good time "
                "for two minutes? I'm calling about {game_title}. We help studios with launch "
                "marketing and community exposure, and I wanted to ask how you are planning "
                "the launch on {platform}."
            ),
            notes="Ask before continuing; offer to call back at a better time.",
        ),
    ),
)
