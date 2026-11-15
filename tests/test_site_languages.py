"""Tests for the Norwegian tree of the site and the language selector.

Cards, translations and glossary entries are fictional. The Norwegian of the fixtures is 'NB ' plus the English text, so
the numbers and sources match and a test can tell translated text from English at a glance. No network, no LLM; the
script test runs Node when it is installed and is skipped otherwise.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from test_site import (
    EN,
    I18N_DIR,
    REPO_ROOT,
    Site,
    built,
    changelog_entries,
    external_resource_refs,
    make_card,
    norm,
    page,
    parse,
    write_card,
    write_yaml,
)

from me_atlas import cards as cardlib
from me_atlas import glossary as gl
from me_atlas import i18n, site
from me_atlas import translations as tr

SLUG = "fictional-hypothesis"
CLAIM = "The fictional hypothesis proposes that widget signalling is altered in patients."
NB_CLAIM = "NB " + CLAIM


@pytest.fixture
def proj_tmp(tmp_path) -> Site:
    return Site(tmp_path)


def nb_files(out: Path) -> list[Path]:
    return sorted((out / "nb").rglob("*.html"))


def en_files(out: Path) -> list[Path]:
    return sorted(p for p in out.rglob("*.html") if p.relative_to(out).parts[0] != "nb")


def rel(out: Path, path: Path) -> str:
    return path.relative_to(out).as_posix()


def write_sidecar(proj: Site, card: dict, *, skip=(), **texts: str) -> Path:
    """A fictional Norwegian file for a card in proj.cards: 'NB ' plus the English text, unless ``texts`` says."""
    english = cardlib.load_card(proj.cards / f"{card['slug']}.yaml")
    items = {}
    for loc, en in tr.english_items(english).items():
        if loc in skip:
            continue
        items[loc] = tr.TItem(
            text=texts.get(loc, "NB " + en.text),
            source_hash=tr.text_hash(en.text),
            sources=list(en.sources) if en.sources is not None else None,
        )
    path = proj.root / "translations" / "nb" / f"{card['slug']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tr.dump_sidecar(tr.TFile(slug=card["slug"], items=items), list(items)), encoding="utf-8")
    return path


def card_with_sidecar(proj: Site, **kw) -> dict:
    card = make_card(SLUG, "Fictional hypothesis", 4, contested_rungs=[4])
    write_card(proj.cards, card)
    write_sidecar(proj, card, **kw)
    return card


def claim_paragraphs(out_page) -> list[str]:
    return [t for t in (norm(p.text()) for p in out_page.find_all("p")) if CLAIM in t]


# --- both trees exist, with the same pages -----


def test_the_norwegian_tree_has_the_same_pages_as_the_english_one(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2), make_card("two", "Fictional two", 0))
    assert [rel(out / "nb", p) for p in nb_files(out)] == [rel(out, p) for p in en_files(out)]
    assert (out / "nb" / "hypotheses" / "one.html").is_file()


def test_both_trees_share_one_stylesheet_and_one_script(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    assert [p.name for p in (out / "static").iterdir()] == ["site.css", "site.js"]
    assert not (out / "nb" / "static").exists()
    doc = page(out, "nb/hypotheses/one.html")
    hrefs = [el.get("href") for el in doc.find_all("link") if el.get("rel") == "stylesheet"]
    assert hrefs == ["../../static/site.css"]
    assert (out / "nb" / "hypotheses" / hrefs[0]).resolve() == (out / "static" / "site.css").resolve()


# --- lang, notice, links both ways -----


def test_every_norwegian_page_says_nb_carries_the_notice_and_links_to_its_english_page(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    pages = nb_files(out)
    assert len(pages) == 7
    for path in pages:
        doc = parse(path.read_text(encoding="utf-8"))
        assert doc.find("html").get("lang") == "nb", path
        notice = doc.find(cls="translation-notice")
        assert notice is not None and "oversettelse av den engelske siden" in norm(notice.text()), path
        english = path.relative_to(out / "nb").as_posix()
        link = notice.find("a")
        assert (path.parent / link.get("href")).resolve() == (out / english).resolve(), path
        selector = doc.find(cls="lang-switch").find_all("a")
        assert [(a.get("data-lang"), a.get("hreflang"), norm(a.text())) for a in selector] == [("en", "en", "English")]
        assert (path.parent / selector[0].get("href")).resolve() == (out / english).resolve(), path


def test_every_english_page_links_to_its_norwegian_page_and_has_no_notice(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    for path in en_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        assert doc.find("html").get("lang") == "en" and doc.find(cls="translation-notice") is None, path
        selector = doc.find(cls="lang-switch").find_all("a")
        assert [(a.get("data-lang"), a.get("hreflang"), a.get("lang"), norm(a.text())) for a in selector] == [
            ("nb", "nb", "nb", "Norsk")
        ]
        target = (path.parent / selector[0].get("href")).resolve()
        assert target == (out / "nb" / rel(out, path)).resolve() and target.is_file(), path


def test_every_page_in_both_trees_lists_all_languages_as_hreflang_alternates(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    for path in en_files(out) + nb_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        alternates = {el.get("hreflang"): el.get("href") for el in doc.find_all("link") if el.get("rel") == "alternate"}
        assert set(alternates) == {"en", "nb", "x-default"}, path
        english = out / path.relative_to(out / "nb") if "nb" in path.relative_to(out).parts[:1] else path
        assert (path.parent / alternates["en"]).resolve() == english.resolve()
        assert (path.parent / alternates["x-default"]).resolve() == english.resolve()
        assert (path.parent / alternates["nb"]).resolve() == (out / "nb" / rel(out, english)).resolve()


def test_navigation_inside_the_norwegian_tree_stays_in_norwegian(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    for path in nb_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        links = doc.find("nav").find_all("a")
        assert [norm(a.text()) for a in links] == [
            "Forside",
            "Hva som er endret",
            "Årsakskart",
            "Hva mangler",
            "Metode",
            "Ordliste",
        ], path
        for a in links:
            assert (path.parent / a.get("href")).resolve().is_relative_to((out / "nb").resolve()), (path, a.get("href"))
        brand = doc.find(cls="brand").find("a")
        assert (path.parent / brand.get("href")).resolve() == (out / "nb" / "index.html").resolve()
    current = [a for a in page(out, "nb/methods.html").find("nav").find_all("a") if a.get("aria-current")]
    assert [norm(a.text()) for a in current] == ["Metode"]


def test_internal_links_and_anchors_all_resolve_in_the_norwegian_tree(proj_tmp):
    write_card(proj_tmp.cards, make_card(SLUG, "Fictional hypothesis", 4, contested_rungs=[4]))
    write_yaml(proj_tmp.cards / "changelog.yaml", changelog_entries())
    assert proj_tmp.build().errors == []
    checked = 0
    for path in nb_files(proj_tmp.out):
        doc = parse(path.read_text(encoding="utf-8"))
        for el in doc.find_all():
            for attr in ("href", "src"):
                value = el.get(attr)
                if not value or re.match(r"^[a-z]+:", value):
                    continue
                target, _, fragment = value.partition("#")
                target_path = path if target == "" else (path.parent / target).resolve()
                assert target_path.is_file(), (path.name, value)
                if fragment:
                    other = doc if target == "" else parse(target_path.read_text(encoding="utf-8"))
                    assert other.find(id=fragment) is not None, (path.name, value)
                checked += 1
    assert checked > 30


# --- language persistence -----


def script_of(path: Path) -> str:
    scripts = [s for s in parse(path.read_text(encoding="utf-8")).find_all("script") if not s.get("src")]
    assert len(scripts) == 1, path
    return "".join(c for c in scripts[0].children if isinstance(c, str))


def test_every_page_in_both_trees_carries_the_persistence_script_and_the_counterpart_mapping(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    for path in en_files(out) + nb_files(out):
        code = "nb" if path.relative_to(out).parts[0] == "nb" else "en"
        script = script_of(path)
        assert 'KEY="me-atlas-lang"' in script and f'HERE="{code}"' in script, path
        assert "location.replace(" in script and "localStorage.getItem" in script, path
        mapping = json.loads(re.search(r"TO=(\{.*?\})[;,]", script).group(1))
        assert set(mapping) == {"en", "nb"}, path
        english = out / path.relative_to(out / "nb") if code == "nb" else path
        assert (path.parent / mapping["en"]).resolve() == english.resolve(), path
        assert (path.parent / mapping["nb"]).resolve() == (out / "nb" / rel(out, english)).resolve(), path
        # the redirect only ever happens in the page's own script, never from a stylesheet or an attribute
        assert 'http-equiv="refresh"' not in path.read_text(encoding="utf-8")


def test_every_storage_access_in_the_script_is_inside_try_catch(proj_tmp):
    script = script_of(built(proj_tmp, make_card("one", "Fictional one", 2)) / "index.html")
    for access in ("localStorage.getItem", "localStorage.setItem"):
        position = script.index(access)
        assert script.rfind("try{", 0, position) != -1, access
        assert script.index("catch(e){}", position) != -1, access


def test_the_script_has_no_network_or_cookie_use_and_no_language_detection(proj_tmp):
    script = script_of(built(proj_tmp, make_card("one", "Fictional one", 2)) / "index.html")
    assert not re.search(r"cookie|navigator|fetch\(|XMLHttpRequest|https?://|\.language", script)


NODE_DRIVER = """
const vm = require('vm');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const results = input.scenarios.map((sc) => {
  const calls = { replace: [], set: [], listeners: [] };
  const ctx = {
    location: { replace: (u) => calls.replace.push(u) },
    document: { addEventListener: (t, f) => calls.listeners.push([t, f]) },
  };
  const storage = sc.storage;
  if (storage === 'getter-throws') {
    Object.defineProperty(ctx, 'localStorage', { get() { throw new Error('denied'); } });
  } else if (storage !== 'absent') {
    ctx.localStorage = {
      getItem: (k) => {
        if (storage === 'get-throws') throw new Error('denied');
        return k in storage ? storage[k] : null;
      },
      setItem: (k, v) => {
        if (storage === 'get-throws' || sc.setThrows) throw new Error('full');
        calls.set.push([k, v]);
      },
    };
  }
  let error = null;
  try { vm.runInNewContext(input.code, ctx); } catch (e) { error = String(e); }
  let clickError = null;
  if (sc.click) {
    try {
      for (const [type, fn] of calls.listeners) {
        const link = sc.click.lang ? { getAttribute: () => sc.click.lang } : null;
        if (type === 'click') fn({ target: { closest: () => link } });
      }
    } catch (e) { clickError = String(e); }
  }
  return { error, clickError, replace: calls.replace, set: calls.set };
});
console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_script_redirects_only_to_a_stored_other_language_and_never_fails(proj_tmp, tmp_path):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    key = "me-atlas-lang"
    scenarios = [
        {"storage": {key: "nb"}},  # 0: stored the other language
        {"storage": {key: "en"}},  # 1: stored the page's own language
        {"storage": {}},  # 2: nothing stored
        {"storage": "get-throws"},  # 3: storage refuses reads
        {"storage": "getter-throws"},  # 4: touching localStorage throws
        {"storage": "absent"},  # 5: no localStorage at all
        {"storage": {key: "xx"}},  # 6: a language the site does not have
        {"storage": {key: "__proto__"}},  # 7: a key that is not a language but exists on every object
        {"storage": {key: "constructor"}},  # 8
        {"storage": {}, "click": {"lang": "nb"}},  # 9: choosing Norsk stores nb
        {"storage": {}, "click": {"lang": None}},  # 10: a click on something else stores nothing
        {"storage": {}, "click": {"lang": "nb"}, "setThrows": True},  # 11: storage full or blocked
        {"storage": "absent", "click": {"lang": "nb"}},  # 12: no storage, a click
    ]

    def run(path: Path) -> list[dict]:
        driver = tmp_path / "driver.js"
        driver.write_text(NODE_DRIVER, encoding="utf-8")
        done = subprocess.run(
            ["node", str(driver)],
            input=json.dumps({"code": script_of(path), "scenarios": scenarios}),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return json.loads(done.stdout)

    english = run(out / "hypotheses" / "one.html")
    assert english[0]["replace"] == ["../nb/hypotheses/one.html"]
    for i in (1, 2, 3, 4, 5, 6, 7, 8):
        assert english[i]["replace"] == [], i
    assert all(r["error"] is None and r["clickError"] is None for r in english)
    assert english[9]["set"] == [[key, "nb"]]
    assert english[10]["set"] == [] and english[11]["set"] == [] and english[12]["set"] == []

    norwegian = run(out / "nb" / "hypotheses" / "one.html")
    assert norwegian[0]["replace"] == []  # stored nb, already on nb
    assert norwegian[1]["replace"] == ["../../hypotheses/one.html"]  # stored en: go to the English counterpart
    assert all(r["error"] is None and r["clickError"] is None for r in norwegian)


# --- the string files -----


def copy_i18n(tmp_path: Path) -> Path:
    target = tmp_path / "i18n"
    shutil.copytree(I18N_DIR, target)
    return target


def edit_strings(directory: Path, lang: str, edit) -> None:
    path = directory / f"{lang}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_a_missing_norwegian_key_fails_the_build_and_names_the_key(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)
    edit_strings(directory, "nb", lambda d: d.pop("card.core_claim"))
    result = proj_tmp.build(i18n_dir=directory)
    assert result.errors == [f"{directory / 'nb.yaml'}: missing key 'card.core_claim'"]
    assert not proj_tmp.out.exists()  # nothing was written


def test_every_missing_key_is_named_and_the_command_line_exits_non_zero(proj_tmp, tmp_path, capsys):
    directory = copy_i18n(tmp_path)
    edit_strings(directory, "nb", lambda d: [d.pop("skip"), d.pop("study.cited_as")])
    assert proj_tmp.run(extra=["--i18n-dir", str(directory)]) == 1
    err = capsys.readouterr().err
    assert "missing key 'skip'" in err and "missing key 'study.cited_as'" in err and "nothing was built" in err


def test_an_unknown_key_a_changed_placeholder_and_a_changed_glossary_term_fail_the_build(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)

    def damage(d):
        d["not.a.key"] = "Ekstra"
        d["level.line"] = "Nivå {nivå} av 5, {name}"
        d["chip.pem_answer"] = "Forklarer [[post-exertional malaise|PEM]]: {answer}"

    edit_strings(directory, "nb", damage)
    errors = proj_tmp.build(i18n_dir=directory).errors
    assert any("unknown key 'not.a.key'" in e for e in errors)
    assert any("key 'level.line' uses placeholders" in e for e in errors)
    assert any("key 'chip.pem_answer' marks glossary terms" in e for e in errors)


def test_a_missing_english_key_stops_the_build_before_any_page_is_rendered(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)
    edit_strings(directory, "en", lambda d: d.pop("answer.yes"))
    errors = proj_tmp.build(i18n_dir=directory).errors
    assert any("unknown key 'answer.yes'" in e for e in errors)  # nb has it, the reference does not


def test_a_banned_norwegian_word_in_a_string_fails_the_build(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)
    edit_strings(directory, "nb", lambda d: d.update({"index.lead": "Et lovende gjennombrudd for [[ME/CFS]]."}))
    errors = proj_tmp.build(i18n_dir=directory).errors
    assert any("banned word 'lovende'" in e and "index.lead" in e for e in errors)
    assert any("banned word 'gjennombrudd'" in e for e in errors)


def test_a_boolean_string_value_and_a_missing_reference_file_fail_the_build(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)
    path = directory / "nb.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("answer.yes: 'ja'", "answer.yes: yes"), encoding="utf-8")
    assert any("key 'answer.yes' must be a string" in e for e in proj_tmp.build(i18n_dir=directory).errors)
    (directory / "en.yaml").unlink()
    assert any("reference language file is missing" in e for e in proj_tmp.build(i18n_dir=directory).errors)


def test_a_glossary_term_marked_in_a_string_must_exist_in_the_glossary(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)
    edit_strings(directory, "en", lambda d: d.update({"index.lead": "About [[no such term]]."}))
    edit_strings(directory, "nb", lambda d: d.update({"index.lead": "Om [[no such term]]."}))
    assert any(
        "marks 'no such term', which is not in the glossary" in e for e in proj_tmp.build(i18n_dir=directory).errors
    )


def test_a_third_language_needs_only_a_string_file(proj_tmp, tmp_path):
    directory = copy_i18n(tmp_path)
    edit_strings(directory, "nb", lambda d: d.update({"lang.name": "Svenska", "skip": "Hoppa till innehållet"}))
    shutil.move(directory / "nb.yaml", directory / "sv.yaml")
    shutil.copy(I18N_DIR / "nb.yaml", directory / "nb.yaml")
    write_card(proj_tmp.cards, make_card("one", "Fictional one", 2))
    assert proj_tmp.build(i18n_dir=directory).errors == []
    out = proj_tmp.out
    assert (out / "sv" / "hypotheses" / "one.html").is_file() and (out / "nb" / "index.html").is_file()
    doc = page(out, "index.html")
    assert [(a.get("data-lang"), norm(a.text())) for a in doc.find(cls="lang-switch").find_all("a")] == [
        ("nb", "Norsk"),
        ("sv", "Svenska"),
    ]
    assert page(out, "sv/index.html").find("html").get("lang") == "sv"
    mapping = json.loads(re.search(r"TO=(\{.*?\})[;,]", script_of(out / "sv" / "index.html")).group(1))
    assert set(mapping) == {"en", "nb", "sv"}
    assert "Hoppa till innehållet" in norm(page(out, "sv/index.html").text())


# --- what the Norwegian page takes from where -----


def test_levels_badges_contested_marks_titles_and_numbers_come_from_the_english_card(proj_tmp):
    card = card_with_sidecar(proj_tmp, name="Fiktiv hypotese")
    assert proj_tmp.build().errors == []
    en, nb = page(proj_tmp.out, f"hypotheses/{SLUG}.html"), page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    assert norm(nb.find("h1").text()) == "Fiktiv hypotese"  # the translated name is used

    def segments(doc):
        return [sorted(s.classes) for s in doc.find("div", "bar").find_all("i", "seg")]

    assert segments(nb) == segments(en)
    assert norm(nb.find(cls="level-line").text()) == "Nivå 4 av 5, Testet med intervensjon"
    chips = [norm(c.text()) for c in nb.find(cls="chips").find_all(cls="chip")]
    assert chips == [
        "Omstridt på trinn 4",
        "Markør validert: ja",
        "Forklarer PEM: ja",
        "Også studert ved langvarig covid",
    ]
    assert norm(nb.find("h2", id="contested").text()) == "Omstridt på trinn 4"

    def titles(doc):
        return [norm(a.text()) for a in doc.find_all("h4", "study-title")]

    assert titles(nb) == titles(en) and titles(nb)  # study titles stay English
    assert [a.get("href") for a in nb.find_all("h4", "study-title")[0].find_all("a")] == [
        a.get("href") for a in en.find_all("h4", "study-title")[0].find_all("a")
    ]

    def sizes(doc):
        return [
            (norm(n.text()), norm(c.text()))
            for n, c in zip(doc.find_all(cls="n-patients"), doc.find_all(cls="n-controls"), strict=True)
        ]

    assert sizes(nb)[0] == ("40 pasienter", "40 kontroller")
    assert sizes(nb)[3] == ("12 pasienter", "kontroller: ingen (ukontrollert studie)")
    assert len(sizes(nb)) == len(sizes(en)) == len(card["studies"])
    meta = norm(nb.find_all("p", "study-meta")[0].text())
    assert "pmid:00000001" in meta and "Canadian Consensus Criteria (CCC)" in meta and "Kontrollert" in meta
    assert "Lavere hos pasienter" in meta and "sitert som [1]" in meta
    last = norm(nb.find(cls="last-checked").text())
    assert last == "Sist kontrollert 2026-10-01 av KI-revisoren."


def test_the_case_definition_quote_is_never_shown_and_a_sidecar_cannot_put_one_there(proj_tmp):
    card = make_card(SLUG, "Fictional hypothesis", 2)
    write_card(proj_tmp.cards, card)
    path = write_sidecar(proj_tmp, card)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["items"]["studies[pmid:00000001].case_definition_quote"] = {"text": "FAKE QUOTE", "source_hash": "0" * 64}
    data["items"]["level"] = {"text": "5", "source_hash": "0" * 64}
    write_yaml(path, data)
    result = proj_tmp.build()
    assert result.errors == []  # an item the English card lacks is ignored, with a warning
    assert any(
        "item 'studies[pmid:00000001].case_definition_quote' does not exist on the English card" in w
        for w in result.translation_warnings
    )
    assert any("item 'level' does not exist on the English card" in w for w in result.translation_warnings)
    nb = norm(page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html").text())
    assert "FAKE QUOTE" not in nb and "Fictional participants met" not in nb
    assert "Nivå 2 av 5" in nb


def test_a_sidecar_with_a_field_the_card_model_has_but_the_sidecar_may_not_fails_the_build(proj_tmp):
    card = make_card(SLUG, "Fictional hypothesis", 2)
    write_card(proj_tmp.cards, card)
    path = write_sidecar(proj_tmp, card)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["level"] = 5
    write_yaml(path, data)
    errors = proj_tmp.build().errors
    assert len(errors) == 1 and "level: Extra inputs are not permitted" in errors[0]
    assert not proj_tmp.out.exists()


def test_the_norwegian_front_page_has_the_same_hypotheses_in_the_same_order_with_translated_names(proj_tmp):
    for card in (make_card("aaa", "Zeta fictional idea", 3), make_card("bbb", "Alpha fictional idea", 3)):
        write_card(proj_tmp.cards, card)
    write_sidecar(proj_tmp, make_card("aaa", "Zeta fictional idea", 3), name="Æ først i alfabetet")
    assert proj_tmp.build().errors == []
    order = lambda doc: [n.get("id").removeprefix("row-") for n in doc.find_all("section", "row")]  # noqa: E731
    en, nb = page(proj_tmp.out, "index.html"), page(proj_tmp.out, "nb/index.html")
    assert order(nb) == order(en) == ["bbb", "aaa"]  # sorted on the English names in both languages
    names = [norm(h.text()) for h in nb.find_all("h3")]
    assert names == ["Alpha fictional idea", "Æ først i alfabetet"]
    assert norm(nb.find("h1").text()) == "Årsaker til ME/CFS: status for evidensen"
    table = nb.find("table", "summary")
    assert [norm(c.text()) for c in table.find_all("th")[:6]] == [
        "Hypotese",
        "Nivå",
        "Omstridt",
        "Markør validert i en uavhengig kohort",
        "Forklarer PEM",
        "Også studert ved langvarig covid",
    ]
    first_row = [norm(c.text()) for c in table.find_all("tr")[1].find_all() if c.tag in ("th", "td")]
    assert first_row[1] == "3: Gjentatt av andre" and first_row[2:] == ["Nei", "Ja", "Ja", "Ja"]


def test_the_norwegian_front_page_ladder_uses_the_norwegian_rung_names_and_meanings(proj_tmp):
    out = built(proj_tmp)
    items = page(out, "nb/index.html").find("ol", "ladder").find_all("li")
    assert [norm(li.find(cls="rung-name").text()) for li in items] == [
        "Foreslått",
        "Første tegn",
        "Støttet i en definert gruppe",
        "Gjentatt av andre",
        "Testet med intervensjon",
        "Årsakssammenheng underbygd",
    ]
    assert (
        norm(items[0].find(cls="rung-meaning").text())
        == "En idé med et begrunnet argument, men ennå ingen direkte pasientdata."
    )
    assert "No hypotheses" not in norm(page(out, "nb/index.html").text())
    assert norm(page(out, "nb/index.html").find(cls="empty").text()) == "Ingen hypoteser er publisert ennå."


# --- fresh, stale, missing, invalid -----


def only_claim(proj: Site, **kw) -> list[str]:
    card_with_sidecar(proj, **kw)
    result = proj.build()
    assert result.errors == []
    return claim_paragraphs(page(proj.out, f"nb/hypotheses/{SLUG}.html"))


def note_after_claim(texts: list[str]) -> bool:
    return any("Denne delen er ikke oversatt ennå." in t for t in texts)


def test_a_fresh_item_shows_norwegian_without_a_note(proj_tmp):
    texts = only_claim(proj_tmp, core_claim="Fiktiv hovedpåstand.")
    assert texts == []  # the English sentence is gone from the page
    nb = page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    assert any(norm(p.text()).startswith("Fiktiv hovedpåstand.") for p in nb.find_all("p"))
    assert not any(
        "Denne delen er ikke oversatt ennå." in norm(p.text())
        for p in nb.find_all("p")
        if "Fiktiv hovedpåstand" in p.text()
    )


def test_a_missing_item_shows_english_with_the_note(proj_tmp):
    texts = only_claim(proj_tmp, skip=("core_claim",))
    assert len(texts) == 1 and texts[0].startswith(CLAIM) and note_after_claim(texts)


def test_a_stale_item_shows_english_with_the_note_and_is_listed_as_a_warning(proj_tmp):
    card = card_with_sidecar(proj_tmp)
    path = proj_tmp.root / "translations" / "nb" / f"{SLUG}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["items"]["core_claim"]["source_hash"] = "f" * 64
    write_yaml(path, data)
    result = proj_tmp.build()
    assert result.errors == []
    texts = claim_paragraphs(page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html"))
    assert len(texts) == 1 and texts[0].startswith(CLAIM) and note_after_claim(texts)
    assert NB_CLAIM not in norm(
        page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html").text()
    )  # stale Norwegian is never shown
    assert (
        f"[nb] {SLUG}: core_claim is stale (the English text changed after it was translated)"
        in result.translation_warnings
    )
    assert card["slug"] == SLUG


def test_an_item_whose_english_sources_changed_shows_english_with_the_note_and_a_stale_warning(proj_tmp):
    card_with_sidecar(proj_tmp)
    path = proj_tmp.root / "translations" / "nb" / f"{SLUG}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["items"]["core_claim"]["sources"] = ["pmid:00000002"]  # the hash is unchanged: only the sources differ
    write_yaml(path, data)
    result = proj_tmp.build()
    assert result.errors == []
    texts = claim_paragraphs(page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html"))
    assert len(texts) == 1 and texts[0].startswith(CLAIM) and note_after_claim(texts)
    assert NB_CLAIM not in norm(page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html").text())
    assert (
        f"[nb] {SLUG}: core_claim is stale (the English sources changed after it was translated)"
        in result.translation_warnings
    )
    assert not any("left out" in w and "core_claim" in w for w in result.translation_warnings)


def test_an_invalid_item_shows_english_with_the_note_and_the_reason_as_a_warning(proj_tmp):
    card = make_card(SLUG, "Fictional hypothesis", 2)
    write_card(proj_tmp.cards, card)
    write_sidecar(proj_tmp, card, **{"studies[pmid:00000001].finding": "NB n=41 pasienter og 40 kontroller."})
    result = proj_tmp.build()
    assert result.errors == []
    nb = page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    finding = norm(nb.find_all("p", "finding")[0].text())
    assert (
        finding.startswith("A study of n=40 patients and 40 controls")
        and "Denne delen er ikke oversatt ennå." in finding
    )
    assert any("studies[pmid:00000001].finding left out: numbers differ" in w for w in result.translation_warnings)
    assert norm(nb.find_all("p", "finding")[1].text()).startswith("NB A study of n=30")  # the others are translated


def test_english_text_on_a_norwegian_page_is_marked_lang_en(proj_tmp):
    only_claim(proj_tmp, skip=("core_claim",))
    nb = page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    spans = [s for s in nb.find_all("span") if s.get("lang") == "en"]
    assert any(CLAIM in norm(s.text()) for s in spans)
    assert all(a.get("lang") == "en" for a in nb.find_all("h4", "study-title") for a in a.find_all("a"))


def test_a_card_with_no_translation_file_says_so_once_and_shows_english(proj_tmp):
    write_card(proj_tmp.cards, make_card(SLUG, "Fictional hypothesis", 4, contested_rungs=[4]))
    result = proj_tmp.build()
    assert result.errors == []
    nb = page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    text = norm(nb.text())
    assert text.count("Dette kortet er ikke oversatt ennå. Teksten under er den engelske originalen.") == 1
    assert "Denne delen er ikke oversatt ennå." not in text
    assert CLAIM in text and norm(nb.find("h1").text()) == "Fictional hypothesis"
    assert nb.find("h1").get("lang") == "en"
    assert result.translation_warnings == [f"[nb] 1 card(s) have no translation file yet: {SLUG}"]


def test_a_stale_name_falls_back_to_english_with_a_note_under_the_heading(proj_tmp):
    card_with_sidecar(proj_tmp, skip=("name",))
    assert proj_tmp.build().errors == []
    nb = page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    assert norm(nb.find("h1").text()) == "Fictional hypothesis" and nb.find("h1").get("lang") == "en"
    assert norm(nb.find("h1").parent.find(cls="untranslated").text()) == "Denne delen er ikke oversatt ennå."


def test_the_english_page_is_the_same_whatever_the_translations_are(proj_tmp, tmp_path):
    card = make_card(SLUG, "Fictional hypothesis", 4, contested_rungs=[4])
    write_card(proj_tmp.cards, card)
    assert proj_tmp.build().errors == []
    before = {rel(proj_tmp.out, p): p.read_text(encoding="utf-8") for p in en_files(proj_tmp.out)}
    write_sidecar(proj_tmp, card)
    assert proj_tmp.build().errors == []
    assert {rel(proj_tmp.out, p): p.read_text(encoding="utf-8") for p in en_files(proj_tmp.out)} == before


def test_a_draft_uses_the_translation_of_the_draft_text_and_the_published_card_keeps_its_own(proj_tmp):
    published = make_card(SLUG, "Fictional published name", 4)
    draft = make_card(SLUG, "Fictional draft name", 4)
    draft["core_claim"]["text"] = "A newer fictional claim."
    write_card(proj_tmp.cards, published)
    write_card(proj_tmp.drafts, draft)
    write_sidecar(proj_tmp, published)  # translated from the published text
    write_yaml(proj_tmp.cards / "changelog.yaml", changelog_entries())
    assert proj_tmp.build(drafts=True).errors == []
    nb = page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html")
    text = norm(nb.text())
    assert "A newer fictional claim." in text and NB_CLAIM not in text  # the draft's claim has no fresh translation
    assert norm(page(proj_tmp.out, "nb/changes.html").find("h2").find("a").text()) == "NB Fictional published name"


# --- the other pages -----


def test_the_norwegian_changes_page_translates_the_frame_and_says_the_entries_are_english(proj_tmp):
    write_card(proj_tmp.cards, make_card(SLUG, "Fictional hypothesis", 4))
    write_yaml(proj_tmp.cards / "changelog.yaml", changelog_entries())
    assert proj_tmp.build().errors == []
    nb = page(proj_tmp.out, "nb/changes.html")
    text = norm(nb.text())
    assert norm(nb.find("h1").text()) == "Hva som er endret"
    assert "Endringsloggen er bare skrevet på engelsk." in text
    assert "Begrunnelse:" in text and "Kilder:" in text and "Beslutningsnivå 2" in text
    assert "A fictional larger study found no difference." in text
    entry_link = nb.find("article", "change").find("h2").find("a")
    assert (
        entry_link.get("href") == f"hypotheses/{SLUG}.html" and (proj_tmp.out / "nb" / entry_link.get("href")).is_file()
    )
    assert "Endringsloggen" not in norm(page(proj_tmp.out, "changes.html").text())


def test_the_norwegian_methods_page_falls_back_to_english_with_a_note(proj_tmp, tmp_path):
    content = tmp_path / "content"
    (content / "methods").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "content" / "methods" / "en.html", content / "methods" / "en.html")
    assert proj_tmp.build(content_dir=content, i18n_dir=I18N_DIR).errors == []
    out = proj_tmp.out
    nb = page(out, "nb/methods.html")
    text = norm(nb.text())
    assert "Metodesiden er ikke oversatt ennå. Teksten under er den engelske originalen." in text
    assert "No medical or research expert has reviewed this content." in text  # the English text
    assert norm(nb.find("h1").text()) == "Methods"
    assert "Metodesiden er ikke oversatt" not in norm(page(out, "methods.html").text())


def test_a_norwegian_methods_text_in_the_content_folder_is_used_without_a_note(proj_tmp, tmp_path):
    content = tmp_path / "content"
    (content / "methods").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "content" / "methods" / "en.html", content / "methods" / "en.html")
    (content / "methods" / "nb.html").write_text(
        '{% from "_macros.html" import gloss with context %}\n<h1>Fiktiv metodeside</h1>\n'
        '<p>Dette er en {{ gloss("hypotheses", "hypotese") }}.</p>\n',
        encoding="utf-8",
    )
    result = proj_tmp.build(content_dir=content, i18n_dir=I18N_DIR)
    assert result.errors == []
    nb = page(proj_tmp.out, "nb/methods.html")
    assert norm(nb.find("h1").text()) == "Fiktiv metodeside"
    assert "ikke oversatt" not in norm(nb.text())
    assert norm(nb.find("button", "term").text()) == "hypotese"


def test_a_missing_english_methods_text_stops_the_build(proj_tmp, tmp_path):
    content = tmp_path / "content"
    (content / "methods").mkdir(parents=True)
    result = proj_tmp.build(content_dir=content, i18n_dir=I18N_DIR)
    assert len(result.errors) == 1 and "the English methods text is missing" in result.errors[0]


def test_draft_builds_show_the_banner_and_noindex_in_norwegian_too(proj_tmp):
    write_card(proj_tmp.drafts, make_card("draft-only", "Fictional draft only", 1))
    assert proj_tmp.build(drafts=True).errors == []
    for path in nb_files(proj_tmp.out):
        doc = parse(path.read_text(encoding="utf-8"))
        assert norm(doc.find(cls="banner").text()) == "Forhåndsvisning av utkast — ikke publisert", path
        assert any(m.get("name") == "robots" and m.get("content") == "noindex" for m in doc.find_all("meta")), path


# --- the glossary in Norwegian -----


GLOSS_EXTRA = [
    {"term": "widget signalling", "aliases": ["signalling"], "explanation": "FICTIONAL: how widgets pass messages."},
    {"term": "unused fictional term", "explanation": "FICTIONAL: appears on no page."},
]
NB_GLOSSARY = [
    {
        "en": "widget signalling",
        "term": "dingsesignalering",
        "aliases": ["signalering av dings"],
        "explanation": "OPPDIKTET: hvordan dingser sender beskjeder.",
    },
    {
        "en": "PEM",
        "term": "PEM",
        "aliases": ["post-eksertusjonell uvelhet"],
        "explanation": "OPPDIKTET: forklaring av PEM.",
    },
]


def glossary_site(tmp_path: Path, nb_entries: list[dict] | None) -> Site:
    proj = Site(tmp_path, GLOSS_EXTRA)
    if nb_entries is not None:
        write_yaml(tmp_path / "glossary.nb.yaml", nb_entries)
    return proj


def marked(doc) -> list[tuple[str, str]]:
    return [(norm(b.text()), b.get("aria-describedby")) for b in doc.find_all("button", "term")]


def test_norwegian_terms_and_aliases_mark_norwegian_text_with_the_norwegian_explanation(tmp_path):
    proj = glossary_site(tmp_path, NB_GLOSSARY)
    card = make_card(SLUG, "Fictional hypothesis", 2)
    card["core_claim"]["text"] = "Fiktiv påstand om widget signalling."
    write_card(proj.cards, card)
    write_sidecar(
        proj, card, core_claim="Dette handler om signalering av dings hos pasienter, og om dingsesignalering igjen."
    )
    assert proj.build().errors == []
    nb = page(proj.out, f"nb/hypotheses/{SLUG}.html")
    words = [w for w, _ in marked(nb)]
    assert "signalering av dings" in words and words.count("dingsesignalering") == 0  # first use of the term only
    tip = nb.find(id="tip-widget-signalling")
    assert norm(tip.text()) == "OPPDIKTET: hvordan dingser sender beskjeder."
    assert ("signalering av dings", "tip-widget-signalling") in marked(nb)


def test_norwegian_marking_is_whole_word_and_case_sensitive(tmp_path):
    proj = glossary_site(tmp_path, NB_GLOSSARY)
    base = gl.load_glossary(proj.glossary)
    marker = site.Marker(gl.localise(base, gl.load_local_glossary(tmp_path / "glossary.nb.yaml", base)).glossary)
    found = lambda text: [text[a:b] for a, b, _ in marker.find(text)]  # noqa: E731
    assert found("Om dingsesignalering og dingsesignaleringer.") == ["dingsesignalering"]
    assert found("Dingsesignalering") == []
    assert found("post-eksertusjonell uvelhet og PEM") == ["post-eksertusjonell uvelhet", "PEM"]
    assert found("widget signalling og signalling") == ["widget signalling", "signalling"]  # English text on the page


def test_english_text_left_on_a_norwegian_page_is_still_marked_with_the_norwegian_explanation(tmp_path):
    proj = glossary_site(tmp_path, NB_GLOSSARY)
    card = make_card(SLUG, "Fictional hypothesis", 2)
    card["core_claim"]["text"] = "Fiktiv påstand om widget signalling."
    write_card(proj.cards, card)
    assert proj.build().errors == []
    nb = page(proj.out, f"nb/hypotheses/{SLUG}.html")
    assert ("widget signalling", "tip-widget-signalling") in marked(nb)
    assert norm(nb.find(id="tip-widget-signalling").text()) == "OPPDIKTET: hvordan dingser sender beskjeder."
    en = page(proj.out, f"hypotheses/{SLUG}.html")
    assert norm(en.find(id="tip-widget-signalling").text()) == "FICTIONAL: how widgets pass messages."


def test_template_labels_in_norwegian_use_the_norwegian_explanation(tmp_path):
    proj = glossary_site(tmp_path, NB_GLOSSARY)
    write_card(proj.cards, make_card(SLUG, "Fictional hypothesis", 2))
    assert proj.build().errors == []
    nb = page(proj.out, f"nb/hypotheses/{SLUG}.html")
    assert ("PEM", "tip-pem") in marked(nb)
    assert norm(nb.find(id="tip-pem").text()) == "OPPDIKTET: forklaring av PEM."
    assert norm(page(proj.out, f"hypotheses/{SLUG}.html").find(id="tip-pem").text()).startswith(
        "Post-exertional malaise."
    )


def test_the_norwegian_glossary_page_lists_norwegian_terms_in_norwegian_order_with_notes_on_the_rest(tmp_path):
    proj = glossary_site(tmp_path, NB_GLOSSARY)
    card = make_card(SLUG, "Fictional hypothesis", 2)
    card["core_claim"]["text"] = "Fiktiv påstand om widget signalling."
    write_card(proj.cards, card)
    assert proj.build().errors == []
    nb = page(proj.out, "nb/glossary.html")
    entries = nb.find("dl", "glossary").find_all("div", "entry")
    terms = [norm(e.find("dt").text()) for e in entries]
    assert terms == sorted(terms, key=lambda t: i18n.sort_key("nb", t))
    by_term = {norm(e.find("dt").text()): e for e in entries}
    assert (
        norm(by_term["dingsesignalering"].find("dd").find("p").text()) == "OPPDIKTET: hvordan dingser sender beskjeder."
    )
    assert "Skrives også: signalering av dings" in norm(by_term["dingsesignalering"].text())
    assert "Ikke oversatt ennå." not in norm(by_term["dingsesignalering"].text())
    untranslated = [t for t, e in by_term.items() if "Ikke oversatt ennå." in norm(e.text())]
    assert untranslated and "dingsesignalering" not in untranslated and "PEM" not in untranslated
    assert "Ordlisten er ikke oversatt ennå" not in norm(nb.text())  # only some terms are missing
    back = by_term["dingsesignalering"].find("dd").find_all("a")
    assert back[0].get("href") == f"hypotheses/{SLUG}.html#use-widget-signalling"
    assert (proj.out / "nb" / back[0].get("href").partition("#")[0]).is_file()
    assert nb.find("h1") is not None and norm(nb.find("h1").text()) == "Ordliste"


def test_without_a_norwegian_glossary_the_page_says_so_once_and_english_explanations_are_used(tmp_path):
    proj = glossary_site(tmp_path, None)
    write_card(proj.cards, make_card(SLUG, "Fictional hypothesis", 2))
    result = proj.build()
    assert result.errors == []
    nb = page(proj.out, "nb/glossary.html")
    text = norm(nb.text())
    assert text.count("Ordlisten er ikke oversatt ennå. Forklaringene under er på engelsk.") == 1
    assert "Ikke oversatt ennå." not in text
    assert norm(page(proj.out, f"nb/hypotheses/{SLUG}.html").find(id="tip-pem").text()).startswith(
        "Post-exertional malaise."
    )


def test_the_english_glossary_page_is_not_changed_by_a_norwegian_glossary(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_nb = glossary_site(tmp_path / "a", NB_GLOSSARY)
    without = glossary_site(tmp_path / "b", None)
    for proj in (with_nb, without):
        write_card(proj.cards, make_card(SLUG, "Fictional hypothesis", 2))
        assert proj.build().errors == []
    for name in ("glossary.html", f"hypotheses/{SLUG}.html", "index.html"):
        assert (with_nb.out / name).read_text(encoding="utf-8") == (without.out / name).read_text(encoding="utf-8")


def test_a_banned_norwegian_word_in_the_norwegian_glossary_fails_the_build(tmp_path):
    bad = [{**NB_GLOSSARY[0], "explanation": "OPPDIKTET: et håp om en kur."}]
    result = glossary_site(tmp_path, bad).build()
    assert any("banned word 'håp'" in e for e in result.errors) and any("banned word 'kur'" in e for e in result.errors)
    assert not (tmp_path / "build").exists()


def test_an_unknown_english_term_in_the_norwegian_glossary_fails_the_build(tmp_path):
    result = glossary_site(tmp_path, [{**NB_GLOSSARY[0], "en": "no such term"}]).build()
    assert any("'en' is 'no such term', which is not a term of the English glossary" in e for e in result.errors)


def test_unused_norwegian_glossary_terms_are_not_reported(tmp_path):
    result = glossary_site(tmp_path, NB_GLOSSARY).build()
    assert result.errors == []
    assert all("dingsesignalering" not in w for w in result.warnings)
    assert "unused fictional term" in result.unused_terms


# --- every page, in Norwegian too -----


def test_every_norwegian_page_has_navigation_footer_statement_build_date_and_one_h1(proj_tmp):
    out = built(proj_tmp, make_card("nav", "Fictional nav", 2))
    for path in nb_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        footer = norm(doc.find("footer").text())
        assert "Ingen medisinsk eller forskningsfaglig ekspert har gjennomgått det." in footer, path
        assert "Bygget 2026-11-01" in footer and "ingen behandlingsråd" in footer, path
        assert len(doc.find_all("h1")) == 1 and doc.find("main") is not None, path


def test_no_norwegian_page_loads_anything_from_another_host_and_files_use_lf(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    for path in nb_files(out):
        assert external_resource_refs(path.read_text(encoding="utf-8")) == [], path
        assert b"\r" not in path.read_bytes()
        path.read_bytes().decode("utf-8")


def test_no_banned_word_on_any_norwegian_page_outside_study_titles(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 4, contested_rungs=[4]))
    for path in nb_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        text = doc.find("body").text(skip_classes=frozenset({"study-title"}))
        for pattern in (cardlib._BANNED_RE, cardlib._BANNED_NB_RE):
            assert not pattern.search(text), path


def test_a_rebuild_removes_the_norwegian_tree_of_the_previous_build(proj_tmp):
    out = built(proj_tmp, make_card("one", "Fictional one", 2))
    stale = out / "nb" / "old.html"
    stale.write_text("old", encoding="utf-8")
    assert proj_tmp.build().errors == []
    assert not stale.exists()


def test_the_build_result_lists_the_norwegian_files_too(proj_tmp):
    write_card(proj_tmp.cards, make_card("listed", "Fictional listed", 2))
    result = proj_tmp.build()
    on_disk = {p for p in proj_tmp.out.rglob("*") if p.is_file() and p.name != site.BUILD_MARKER}
    assert set(result.written) == on_disk
    assert {p.relative_to(proj_tmp.out).as_posix() for p in on_disk if p.suffix == ".html"} >= {
        "nb/index.html",
        "nb/hypotheses/listed.html",
        "hypotheses/listed.html",
    }


def test_translation_warnings_are_printed_by_the_command_line(proj_tmp, capsys):
    card_with_sidecar(proj_tmp, skip=("core_claim", "subgroups[0]"))
    assert proj_tmp.run() == 0
    err = capsys.readouterr().err
    assert f"warning: [nb] {SLUG}: 2 of 13 item(s) not translated yet" in err


def test_the_language_names_in_the_selector_come_from_the_language_files(proj_tmp):
    out = built(proj_tmp)
    assert norm(page(out, "index.html").find(cls="lang-switch").text()) == "Norsk"
    assert norm(page(out, "nb/index.html").find(cls="lang-switch").text()) == "English"
    assert EN["lang.name"] == "English"


def test_a_sidecar_item_the_english_card_lacks_is_printed_as_a_warning_by_the_command_line(proj_tmp, capsys):
    card = make_card(SLUG, "Fictional hypothesis", 2)
    write_card(proj_tmp.cards, card)
    path = write_sidecar(proj_tmp, card)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["items"]["unknown_field[0]"] = data["items"]["subgroups[0]"]
    write_yaml(path, data)
    assert proj_tmp.run() == 0
    err = capsys.readouterr().err
    assert f"warning: [nb] {SLUG}: item 'unknown_field[0]' does not exist on the English card" in err


def test_a_translation_file_for_a_card_that_is_not_in_the_build_is_a_warning(proj_tmp):
    card = make_card("gone", "Fictional gone", 2)
    write_card(proj_tmp.cards, card)
    write_sidecar(proj_tmp, card)
    (proj_tmp.cards / "gone.yaml").unlink()
    write_card(proj_tmp.cards, make_card("other", "Fictional other", 2))
    result = proj_tmp.build()
    assert result.errors == []
    assert (
        "[nb] gone: a translation file exists but this build has no English card 'gone'" in result.translation_warnings
    )


# --- the causal map page in Norwegian -----


def nb_map_project(proj: Site, tmp_path: Path, *, translate_link: bool = True, nb_content: bool = True):
    """Two cards, one link between them and one to a symptom. Both cards and the symptom are translated, so a note on
    a link sentence can only come from the link text itself."""
    from test_site_map import map_content, map_link

    content = map_content(tmp_path)
    first = make_card(
        "first-idea",
        "Fictional first idea",
        2,
        layer="trigger",
        links=[
            map_link("second-idea", "A fictional review proposes a link."),
            map_link("symptom:fatigue", "A fictional link to fatigue."),
        ],
    )
    second = make_card("second-idea", "Fictional second idea", 1, layer="mechanism")
    write_card(proj.cards, first)
    write_card(proj.cards, second)
    skip = () if translate_link else ("links[1]",)
    write_sidecar(proj, first, skip=skip, **{"links[0]": "NB En fiktiv oversikt foreslår en lenke."})
    write_sidecar(proj, second)
    if nb_content:
        write_yaml(content / "symptoms.nb.yaml", [{"id": "fatigue", "name": "Fiktiv utmattelse"}])
    return content


def test_the_norwegian_map_uses_fresh_link_texts_and_norwegian_labels(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path)
    assert proj_tmp.build(content_dir=content).errors == []
    doc = page(proj_tmp.out, "nb/map.html")
    assert doc.find("html").get("lang") == "nb"
    assert norm(doc.find("h1").text()) == "Årsakskart"
    assert [norm(h.text()) for h in doc.find_all("h2") if (h.get("id") or "").startswith("layer-")] == [
        "Disposisjon",
        "Utløser",
        "Vedlikeholdende mekanisme",
        "Målbar dysfunksjon",
        "Symptom",
    ]
    items = doc.find("article", id="card-first-idea").find_all("li")
    assert "NB En fiktiv oversikt foreslår en lenke. — foreslått [1]" in norm(items[0].text())
    assert items[0].find(cls="untranslated") is None
    assert items[0].find("a", "ref").get("href") == "hypotheses/first-idea.html#study-pmid:00000001"


def test_a_link_text_without_a_fresh_translation_is_english_with_the_note(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path, translate_link=False)
    assert proj_tmp.build(content_dir=content).errors == []
    items = page(proj_tmp.out, "nb/map.html").find("article", id="card-first-idea").find_all("li")
    english = [s for s in items[1].find_all("span") if s.get("lang") == "en"]
    assert [norm(e.text()) for e in english] == ["A fictional link to fatigue."]
    assert "Denne delen er ikke oversatt ennå." in norm(items[1].text())
    assert "Denne delen er ikke oversatt ennå." not in norm(items[0].text())


def test_a_card_without_a_norwegian_file_has_its_links_in_english_with_the_note(proj_tmp, tmp_path):
    from test_site_map import map_content, map_link

    content = map_content(tmp_path)
    write_card(
        proj_tmp.cards,
        make_card(
            "only-en", "Fictional only en", 1, layer="trigger", links=[map_link("symptom:fatigue", "English only.")]
        ),
    )
    assert proj_tmp.build(content_dir=content).errors == []
    item = page(proj_tmp.out, "nb/map.html").find("article", id="card-only-en").find("li")
    assert "English only." in norm(item.text()) and "Denne delen er ikke oversatt ennå." in norm(item.text())


def test_support_labels_are_norwegian(proj_tmp, tmp_path):
    from test_site_map import map_content, map_link

    content = map_content(tmp_path)
    links = [
        map_link("symptom:fatigue", "One.", "proposed"),
        map_link("question:own", "Two.", "associated"),
        map_link("question:asked", "Three.", "directional", ["pmid:00000002"]),
    ]
    write_card(proj_tmp.cards, make_card("labels", "Fictional labels", 1, layer="trigger", links=links))
    assert proj_tmp.build(content_dir=content).errors == []
    text = [
        norm(li.text()) for li in page(proj_tmp.out, "nb/map.html").find("article", id="card-labels").find_all("li")
    ]
    assert [t.split(": ", 1)[1].split(" [")[0].split(" — ")[1] for t in text] == [
        "foreslått",
        "samvariasjon",
        "retning støttet",
    ]


def test_norwegian_symptom_and_question_texts_come_from_the_nb_content_files(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path)
    write_yaml(content / "open-questions.nb.yaml", [{"id": "own", "text": "Hva holder det fiktive signalet nede?"}])
    assert proj_tmp.build(content_dir=content).errors == []
    doc = page(proj_tmp.out, "nb/map.html")
    assert norm(doc.find(id="symptom-fatigue").text()).startswith("Fiktiv utmattelse")
    assert "Hva holder det fiktive signalet nede?" in norm(doc.find(id="question-own").text())
    assert "Prosjektets eget spørsmål, ikke stilt i en publikasjon" in norm(doc.find(id="question-own").text())
    assert "Stilt i:" in norm(doc.find(id="question-asked").text())
    # no note on the translated ones; the question without a translation is English with the note
    assert "ikke oversatt" not in norm(doc.find(id="symptom-fatigue").text())
    asked = doc.find(id="question-asked")
    assert "What starts the fictional change?" in norm(asked.text()) and "Denne delen er ikke oversatt ennå." in norm(
        asked.text()
    )
    assert any(s.get("lang") == "en" for s in asked.find_all("span"))
    # the English page is untouched by the Norwegian files
    assert "Fiktiv utmattelse" not in (proj_tmp.out / "map.html").read_text(encoding="utf-8")


def test_without_nb_content_files_symptoms_and_questions_fall_back_to_english_with_the_note(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path, nb_content=False)
    assert proj_tmp.build(content_dir=content).errors == []
    node = page(proj_tmp.out, "nb/map.html").find(id="symptom-fatigue")
    assert "Fictional fatigue" in norm(node.text()) and "Denne delen er ikke oversatt ennå." in norm(node.text())


def test_an_nb_content_entry_for_an_unknown_id_stops_the_build(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path)
    write_yaml(content / "symptoms.nb.yaml", [{"id": "ghost", "name": "Spøkelse"}])
    result = proj_tmp.build(content_dir=content)
    assert any("'ghost' is not an id of the English file" in e for e in result.errors)
    assert not proj_tmp.out.exists()


def test_the_norwegian_convergence_labels_and_counts(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path)
    assert proj_tmp.build(content_dir=content).errors == []
    doc = page(proj_tmp.out, "nb/map.html")
    assert norm(doc.find("h2", id="common-mechanisms").text()) == "Kandidater til felles mekanisme"
    assert norm(doc.find("h2", id="roots").text()) == "Kandidater til rot"
    roots = doc.find(cls="map-convergence")
    assert [norm(li.text()) for li in roots.find_all("li")] == ["NB Fictional first idea — 2 lenker ut"]


def test_every_map_string_exists_in_both_languages_with_the_same_placeholders():
    en = i18n.load_strings(I18N_DIR / "en.yaml")
    nb = i18n.load_strings(I18N_DIR / "nb.yaml")
    keys = [k for k in en if k.startswith(("map.", "gaps.", "layer.", "support.")) or k in ("page.map", "page.gaps")]
    assert len(keys) >= 25 and all(k in nb for k in keys)
    assert i18n.compare(en, nb, "nb") == []


def test_a_link_translation_whose_numbers_differ_is_left_out_of_the_map_with_a_warning(proj_tmp, tmp_path):
    from test_site_map import map_content, map_link

    content = map_content(tmp_path)
    card = make_card(
        "numbers",
        "Fictional numbers",
        1,
        layer="trigger",
        links=[map_link("symptom:fatigue", "A fictional study of 40 patients found a relation.")],
    )
    write_card(proj_tmp.cards, card)
    write_sidecar(proj_tmp, card, **{"links[0]": "NB En fiktiv studie av 400 pasienter fant en sammenheng."})
    result = proj_tmp.build(content_dir=content)
    assert result.errors == []
    assert any("numbers" in w and "links[0]" in w for w in result.translation_warnings)
    item = page(proj_tmp.out, "nb/map.html").find("article", id="card-numbers").find("li")
    assert "A fictional study of 40 patients found a relation." in norm(item.text())
    assert "400" not in norm(item.text()) and "Denne delen er ikke oversatt ennå." in norm(item.text())


def test_the_norwegian_drawing_uses_norwegian_labels_and_marks_english_nodes(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path)
    assert proj_tmp.build(content_dir=content).errors == []
    doc = page(proj_tmp.out, "nb/map.html")
    whole = doc.find("details", cls="map-whole")
    assert norm(whole.find("summary").text()) == "Vis hele kartet"
    svg = whole.find("svg")
    labels = [norm(t.text()) for t in svg.find_all("text", cls="band-label")]
    assert labels == ["Disposisjon", "Utløser", "Vedlikeholdende mekanisme", "Målbar dysfunksjon", "Symptom"]
    nodes = {a.get("data-key"): a for a in svg.find_all("a") if "node" in a.classes}
    assert "Nivå 2" in nodes["first-idea"].text() and "2 ut" in nodes["first-idea"].text()
    assert "Fiktiv utmattelse" in nodes["symptom:fatigue"].text() and nodes["symptom:fatigue"].get("lang") is None
    assert nodes["question:asked"].get("lang") == "en"  # no Norwegian text for this question
    assert nodes["first-idea"].get("href") == "hypotheses/first-idea.html"
    legend = norm(doc.find("div", cls="map-legend").text())
    assert "Slik leser du tegningen" in legend and "Foreslått lenke" in legend
    assert "Level" not in norm(svg.text())


def test_the_english_drawing_is_not_changed_by_norwegian_files(proj_tmp, tmp_path):
    content = nb_map_project(proj_tmp, tmp_path)
    assert proj_tmp.build(content_dir=content).errors == []
    text = (proj_tmp.out / "map.html").read_text(encoding="utf-8")
    assert "Nivå" not in text and "Fiktiv utmattelse" not in text and "Level 2" in text


def test_an_obsolete_item_is_never_shown_and_is_listed_as_a_warning(proj_tmp):
    card_with_sidecar(proj_tmp)  # the card has no links
    path = proj_tmp.root / "translations" / "nb" / f"{SLUG}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["items"]["links[0]"] = {"text": "OBSOLETE-NB-LINK-TEXT", "sources": ["pmid:00000001"], "source_hash": "a" * 64}
    write_yaml(path, data)
    result = proj_tmp.build()
    assert result.errors == []
    assert f"[nb] {SLUG}: links[0] is obsolete (the English item was removed)" in result.translation_warnings
    assert "OBSOLETE-NB-LINK-TEXT" not in page(proj_tmp.out, f"nb/hypotheses/{SLUG}.html").text()
