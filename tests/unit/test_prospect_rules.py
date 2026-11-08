from __future__ import annotations

from tg_sales.domain.prospects import (
    DuplicateCandidate,
    MatchStrength,
    OrganizationIndex,
    OrganizationKey,
    merge_tags,
    name_conflicts_with_domain,
    name_similarity,
    significant_words,
)

INDEX = OrganizationIndex(
    [
        OrganizationKey("1", "Pixel Forge Studios", "pixelforge.example"),
        OrganizationKey("2", "Moon Owl Games", None),
        OrganizationKey("3", "Pixel Forge", "other-forge.example", archived=True),
        OrganizationKey("4", "Itch Hosted", "itch.io"),
        OrganizationKey("5", "Northwind GmbH", "northwind.example"),
    ]
)


def strengths(found: list[DuplicateCandidate]) -> list[tuple[str, MatchStrength]]:
    return [(c.id, c.strength) for c in found]


def test_same_domain_is_strong() -> None:
    found = INDEX.find("Totally Different Name", "pixelforge.example")
    assert strengths(found) == [("1", MatchStrength.STRONG)]


def test_contact_email_is_strong() -> None:
    found = INDEX.find("New Co", None, email_matches={"2": "ana@moonowl.example"})
    assert strengths(found) == [("2", MatchStrength.STRONG)]
    assert "ana@moonowl.example" in found[0].reason


def test_shared_host_domain_is_not_evidence() -> None:
    assert INDEX.find("Another Itch Dev", "itch.io") == []


def test_name_matches_ignore_case_punctuation_and_company_form() -> None:
    assert strengths(INDEX.find("northwind", None)) == [("5", MatchStrength.NAME)]
    assert strengths(INDEX.find("MOON-OWL games!", None)) == [("2", MatchStrength.NAME)]


def test_similar_names_are_suggestions() -> None:
    found = INDEX.find("Pixel Forge Studio", None)
    assert ("1", MatchStrength.SIMILAR) in strengths(found)
    archived = next(c for c in INDEX.find("Pixel Forge", None) if c.id == "3")
    assert archived.archived


def test_results_are_strongest_first_and_exclude_self() -> None:
    found = INDEX.find("Pixel Forge", "pixelforge.example")
    assert found[0].id == "1" and found[0].strength is MatchStrength.STRONG
    assert all(c.id != "1" for c in INDEX.find("Pixel Forge Studios", None, exclude_id="1"))


def test_name_conflicts_with_domain() -> None:
    candidate = DuplicateCandidate("1", "X", "a.example", MatchStrength.NAME, "Same name")
    assert name_conflicts_with_domain(candidate, "b.example")
    assert not name_conflicts_with_domain(candidate, "a.example")
    assert not name_conflicts_with_domain(candidate, None)
    assert not name_conflicts_with_domain(candidate, "gmail.com")


def test_name_similarity() -> None:
    assert name_similarity("Pixel Forge Inc", "pixel forge") == 1.0
    assert name_similarity("Alpha", "Omega") < 0.5
    assert name_similarity("", "x") == 0.0


def test_merge_tags() -> None:
    assert merge_tags(["Indie", "vr"], ["indie", " Mobile ", "", "VR", "pc"]) == (
        "Indie",
        "vr",
        "Mobile",
        "pc",
    )


def test_significant_words_ignore_common_studio_words() -> None:
    assert significant_words("The Pixel Forge Games Studio, Inc.") == ["pixel", "forge"]
    assert significant_words("Games Studio") == []


def test_similar_names_compared_only_on_distinctive_words() -> None:
    keys = [OrganizationKey(str(i), f"Studio {i} Games", None) for i in range(2000)]
    keys.append(OrganizationKey("pf", "Pixel Forge Studios", None))
    index = OrganizationIndex(keys)
    # "Studio 7 Games" shares only common words with the others: no false matches.
    assert [c.id for c in index.find("Studio 7 Games", None)] == ["7"]
    assert [c.id for c in index.find("Pixel Forge Studio", None)] == ["pf"]
