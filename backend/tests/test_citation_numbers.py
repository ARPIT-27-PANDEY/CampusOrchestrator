"""The numeric claim check: numbers in cited sentences must occur in a cited passage from that page."""

from __future__ import annotations

from app.agent.citations import verify_citations
from app.agent.models import Citation

CITE = Citation(
    number=1,
    citation_id="c1",
    document_title="UG Ordinances and Regulations 2025",
    source_filename="iitr-ug-ordinance-2025.pdf",
    document_version="v",
    page=25,
    excerpt="A student may register for a minimum of 14 credits and a maximum of 24 credits in a semester.",
    source_url="https://iitr.ac.in/x.pdf",
)


def test_supported_numbers_pass() -> None:
    answer = "You may register for 14 to 24 credits per semester [UG Ordinances and Regulations 2025, p. 25]."
    check = verify_citations(answer, [CITE])
    assert check.ok and check.numbers_checked == 2 and check.unsupported_numbers == []


def test_number_not_in_the_cited_passage_is_flagged() -> None:
    answer = "You may register for up to 30 credits per semester [UG Ordinances and Regulations 2025, p. 25]."
    check = verify_citations(answer, [CITE])
    assert check.ok  # the page reference itself is valid ...
    assert check.unsupported_numbers == ["30"]  # ... but the number is not supported by that page


def test_uncited_sentences_and_page_numbers_are_not_counted() -> None:
    answer = "Campus has 23 departments. See p. 25 for credits [UG Ordinances and Regulations 2025, p. 25]."
    check = verify_citations(answer, [CITE])
    assert check.numbers_checked == 0  # "23" is in an uncited sentence; "p. 25" is a reference, not a claim
