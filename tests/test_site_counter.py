"""Tests for the optional GoatCounter visit counter in the built site. Offline; fictional cards."""

from __future__ import annotations

import pytest
from test_site import Site, built, make_card, page, write_card

from me_atlas import site

ENDPOINT = "https://me-atlas.goatcounter.com/count"
SRC = "https://gc.zgo.at/count.v5.js"
INTEGRITY = "sha384-atnOLvQb9t+jTSipvd75X2yginT4PjVbqDdlJAmxMm+wYElFmeR6EmLP5bYeoRVQ"
# The methods text names GoatCounter and links its privacy page, so the plain word is not a marker.
MARKERS = ("data-goatcounter", "goatcounter.com/count", "gc.zgo.at")


@pytest.fixture
def proj(tmp_path) -> Site:
    return Site(tmp_path)


def card():
    return make_card("fictional-hypothesis", "Fictional hypothesis", 2)


def pages(out):
    return sorted(out.rglob("*.html"))


def build_with_counter(proj: Site, code: str = "me-atlas", **options):
    write_card(proj.cards, card())
    result = proj.build(goatcounter=code, **options)
    assert result.errors == []
    return proj.out


def test_every_page_in_both_languages_has_exactly_one_counter_tag(proj: Site):
    out = build_with_counter(proj)
    files = pages(out)
    assert any(p.parent.name == "nb" for p in files) and any(p.parent == out for p in files)
    assert any("fictional-hypothesis" in p.name for p in files)  # a card page is among them
    for path in files:
        rel = path.relative_to(out).as_posix()
        tags = [s for s in page(out, rel).find_all("script") if s.get("data-goatcounter") is not None]
        assert len(tags) == 1, rel
        tag = tags[0]
        assert tag.get("data-goatcounter") == ENDPOINT, rel
        assert tag.get("src") == SRC and tag.get("crossorigin") == "anonymous", rel
        assert tag.get("integrity") == INTEGRITY and "async" in tag.attrs, rel
        assert tag.parent.tag == "head", rel
        assert path.read_text(encoding="utf-8").count("goatcounter.com/count") == 1, rel


def test_the_code_is_only_taken_from_the_option(proj: Site):
    out = build_with_counter(proj, "other-site-9")
    assert "https://other-site-9.goatcounter.com/count" in (out / "index.html").read_text(encoding="utf-8")
    assert "me-atlas.goatcounter" not in (out / "index.html").read_text(encoding="utf-8")


def test_no_counter_without_the_option(proj: Site):
    out = built(proj, card())
    assert pages(out)
    for path in (p for p in out.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        assert not any(m in text for m in MARKERS), path.name


def test_a_draft_build_never_counts_even_with_the_option(proj: Site):
    write_card(proj.cards, card())
    assert proj.build(drafts=True, goatcounter="me-atlas").errors == []
    assert pages(proj.out)
    for path in (p for p in proj.out.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        assert not any(m in text for m in MARKERS), path.name


def test_only_html_pages_carry_the_counter(proj: Site):
    out = build_with_counter(proj)
    others = [p for p in out.rglob("*") if p.is_file() and p.suffix != ".html"]
    assert others
    for path in others:
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        assert not any(m in text for m in MARKERS), path.name


@pytest.mark.parametrize("code", ["ME Atlas", "me.atlas", 'x"><script>', "", "Me-Atlas", "a" * 64, "-é"])
def test_an_invalid_code_fails_the_build_and_writes_nothing(proj: Site, code):
    write_card(proj.cards, card())
    result = proj.build(goatcounter=code)
    assert result.errors and "GoatCounter" in result.errors[0]
    assert not proj.out.exists()


@pytest.mark.parametrize("code", ["a", "me-atlas", "a" * 63, "0-9"])
def test_valid_codes_are_accepted(proj: Site, code):
    build_with_counter(proj, code)


def test_the_command_line_option_sets_the_counter_and_rejects_a_bad_code(proj: Site):
    write_card(proj.cards, card())
    assert proj.run(extra=["--goatcounter", "me-atlas"]) == 0
    assert ENDPOINT in (proj.out / "index.html").read_text(encoding="utf-8")
    assert proj.run(extra=["--goatcounter", "bad code"]) == 1
    assert site.GOATCOUNTER_CODE.fullmatch("me-atlas")


def test_the_page_without_javascript_has_no_noscript_pixel(proj: Site):
    out = build_with_counter(proj)
    assert (out / "index.html").read_text(encoding="utf-8").lower().count("<noscript") == 0
