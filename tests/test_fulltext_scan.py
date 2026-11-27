"""Tests for the full-text scan (``me_atlas.fulltext_scan`` and the ``scan-*`` commands of ``me_atlas.fulltext``).

Fictional PMIDs, PMCIDs and cards built in tmp_path (helpers from test_citations). No network, no LLM: the scan
agent's files are written by the tests.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
import yaml
from test_citations import (
    QUOTE,
    add_fulltext,
    add_page,
    add_record,
    make_study,
    write_card,
)

from me_atlas import cards, europepmc, fulltext, fulltext_scan, pipeline

SLUG = "fictional-scan-card"
AGREES_ID = "90000201"  # card CCC, full text names the Canadian criteria
UNVERIFIED_ID = "90000202"  # card unverified, full text names Fukuda
FUKUDA_ID = "90000203"  # card Fukuda, full text names only CCC
GENERIC_ID = "90000204"  # card Fukuda, quote absent, full text has only a generic sentence
PAGE_ID = "90000205"  # context, unverified, a cached PMC page naming Holmes
PDF_ID = "90000206"  # supports, the XML is a PDF placeholder
NOTHING_ID = "90000207"  # supports, nothing cached
CCC_QUOTE = "Participants met the Canadian Consensus Criteria."
FUKUDA_TEXT = "Participants met the 1994 Fukuda criteria."
GENERIC_TEXT = "Participants were selected by the diagnostic criteria of the clinic."
ONLY_IN_FULLTEXT = "The median disease duration was nine years."
CARD_ONLY = "CARD-ONLY-SENTENCE about widgets."


def lookup_only(root: Path, pmid: str, pmcid: str) -> None:
    folder = root / "europepmc"
    folder.mkdir(parents=True, exist_ok=True)
    hit = {"id": pmid, "source": "MED", "pmid": pmid, "pmcid": pmcid, "isOpenAccess": "Y", "inPMC": "Y"}
    (folder / f"{pmid}.json").write_text(json.dumps({"hitCount": 1, "resultList": {"result": [hit]}}), encoding="utf-8")


def build(tmp: Path) -> tuple[Path, Path]:
    """The cache and the cards directory: one card, seven studies covering each step 0 label and the unread statuses."""
    root = tmp / "cache"
    for pmid in (AGREES_ID, UNVERIFIED_ID, FUKUDA_ID, GENERIC_ID, PAGE_ID, PDF_ID, NOTHING_ID):
        add_record(root, pmid)
    add_fulltext(root, AGREES_ID, "PMC9200001", (CCC_QUOTE, ONLY_IN_FULLTEXT))
    add_fulltext(root, UNVERIFIED_ID, "PMC9200002", (FUKUDA_TEXT, ONLY_IN_FULLTEXT))
    add_fulltext(root, FUKUDA_ID, "PMC9200003", ("All fictional participants fulfilled the Canadian criteria.",))
    add_fulltext(root, GENERIC_ID, "PMC9200004", (GENERIC_TEXT,))
    add_page(root, PAGE_ID, "PMC9200005", body="<p>Participants met the Holmes criteria.</p>")
    lookup_only(root, PDF_ID, "PMC9200006")
    (root / "europepmc" / "PMC9200006.xml").write_text(
        "<article><body><p>The full text is available as a PDF.</p></body></article>", encoding="utf-8"
    )
    studies = [
        make_study(AGREES_ID, role="supports", case_definition="CCC", case_definition_quote=CCC_QUOTE),
        make_study(
            UNVERIFIED_ID,
            case_definition="unverified",
            case_definition_source=None,
            case_definition_quote=None,
        ),
        make_study(FUKUDA_ID, role="supports", case_definition="Fukuda", case_definition_quote=QUOTE),
        make_study(GENERIC_ID, role="supports", case_definition="Fukuda", case_definition_quote=QUOTE),
        make_study(PAGE_ID, case_definition="unverified", case_definition_source=None, case_definition_quote=None),
        make_study(PDF_ID, role="supports", case_definition="Fukuda", case_definition_quote=QUOTE),
        make_study(NOTHING_ID, role="supports", case_definition="Fukuda", case_definition_quote=QUOTE),
    ]
    path = write_card(tmp / "cards", studies, SLUG)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["core_claim"] = {"text": CARD_ONLY, "sources": [f"pmid:{AGREES_ID}"]}
    data["level_reason"] = {"text": "Fictional reason from the first study.", "sources": [f"pmid:{AGREES_ID}"]}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    cards.load_card(path)  # the fixture card validates
    return root, tmp / "cards"


class Scan:
    """A scan run folder over the fictional cache and cards."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.cache, self.cards = build(tmp)
        self.out = tmp / "run"

    def plan(self, *extra: str) -> int:
        return fulltext.main(
            [
                "scan-plan",
                "--out",
                str(self.out),
                "--cache-dir",
                str(self.cache),
                "--cards-dir",
                str(self.cards),
                *extra,
            ]
        )

    def record(self) -> int:
        return fulltext.main(["scan-record", "--out", str(self.out)])

    def plan_json(self) -> dict:
        return json.loads((self.out / "scan-plan.json").read_text(encoding="utf-8"))

    def entry(self, study: str) -> dict:
        return next(s for s in self.plan_json()["studies"] if s["study"] == f"pmid:{study}")

    def write_scan(self, study: str, **fields: dict) -> Path:
        """The scan file of a study: every field confirmed (carrying not_cited when uncited) except ``fields``."""
        entry = self.entry(study)
        data = {
            name: {"verdict": "confirmed", "quote": None, "note": None}
            for name in fulltext_scan.FIELDS
            if name != "carrying"
        }
        data["carrying"] = (
            {"verdict": "confirmed", "quote": None, "note": None}
            if entry["cited_in_reason"]
            else {"verdict": "not_cited", "quote": None, "note": None}
        )
        data.update(fields)
        path = self.out / entry["scan_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"card": SLUG, "study": f"pmid:{study}", "fields": data}), encoding="utf-8", newline="\n"
        )
        return path

    def raw_scan(self, study: str, text: str) -> Path:
        path = self.out / self.entry(study)["scan_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def result(self) -> dict:
        return json.loads((self.out / "scan-result.json").read_text(encoding="utf-8"))

    def report(self) -> str:
        return (self.out / "scan-report.md").read_text(encoding="utf-8")

    def record_of(self, study: str) -> dict:
        return self.result()["cards"][SLUG]["studies"][f"pmid:{study}"]

    def context(self, study: str) -> str:
        return (self.out / self.entry(study)["context"]).read_text(encoding="utf-8")


@pytest.fixture
def scan(tmp_path: Path) -> Scan:
    return Scan(tmp_path)


def differs(quote: str, note: str = "The full text says so.") -> dict:
    return {"verdict": "differs", "quote": quote, "note": note}


# --- step 0 ------------------------------------------------------------------------------------------------------


def labels(scan: Scan) -> dict[str, str]:
    scan.plan()
    return {
        s["study"]: s["label"] for s in json.loads((scan.out / "step0.json").read_text(encoding="utf-8"))["studies"]
    }


def test_step0_agrees_when_the_full_text_names_the_cards_definition(scan: Scan):
    assert labels(scan)[f"pmid:{AGREES_ID}"] == "agrees"


def test_step0_differs_when_a_card_at_unverified_meets_a_named_definition(scan: Scan):
    assert labels(scan)[f"pmid:{UNVERIFIED_ID}"] == "differs"


def test_step0_differs_when_a_card_at_fukuda_meets_only_the_canadian_criteria(scan: Scan):
    assert labels(scan)[f"pmid:{FUKUDA_ID}"] == "differs"


def test_step0_no_candidate_for_a_generic_sentence_and_a_quote_that_is_absent(scan: Scan):
    assert labels(scan)[f"pmid:{GENERIC_ID}"] == "no_candidate"


def test_step0_reads_a_pmc_page_with_the_page_finder(scan: Scan):
    assert labels(scan)[f"pmid:{PAGE_ID}"] == "differs"  # the page names Holmes; the card is at unverified


def test_step0_labels_only_xml_and_page_studies_and_gives_the_others_no_context(scan: Scan):
    found = labels(scan)
    assert set(found) == {f"pmid:{i}" for i in (AGREES_ID, UNVERIFIED_ID, FUKUDA_ID, GENERIC_ID, PAGE_ID)}
    names = {p.name for p in (scan.out / "scan-context").iterdir()}
    assert not any(PDF_ID in n or NOTHING_ID in n for n in names)
    assert len(names) == 5


def test_step0_alone_flags_nothing(scan: Scan):
    scan.plan()
    assert not (scan.out / "scan-result.json").exists() and not (scan.out / "requests").exists()


@pytest.mark.parametrize(
    "words, names",
    [
        (("Fukuda",), {"Fukuda"}),
        (("1994 criteria of the CDC",), {"Fukuda"}),
        (("CDC",), set()),
        (("CDC", "diagnostic criteria", "case definition"), set()),
        (("Holmes",), {"Holmes1988"}),
        (("Canadian Consensus", "CCC"), {"CCC"}),
        (("SEID",), {"IOM2015"}),
        (("Oxford", "Sharpe"), {"Oxford"}),
        (("International Consensus Criteria",), {"ICC"}),
    ],
)
def test_named_definitions_sort_the_matched_wording(words, names):
    assert fulltext_scan.named_definitions(words) == names


# --- scan-plan ---------------------------------------------------------------------------------------------------


def test_scan_plan_writes_the_plan_with_each_cards_sha256_and_only_inside_run(scan: Scan, monkeypatch):
    class Raises:
        def __init__(self, *a, **k):
            raise AssertionError("a client was made: scan-plan must be offline")

    def no_connect(*a, **k):
        raise AssertionError("a connection was opened: scan-plan must be offline")

    monkeypatch.setattr(europepmc, "EuropePmcClient", Raises)
    monkeypatch.setattr(pipeline, "live_fulltext_loader", Raises)
    monkeypatch.setattr(socket.socket, "connect", no_connect)
    before = {p for p in scan.tmp.rglob("*") if p.is_file()}
    assert scan.plan() == 0
    after = {p for p in scan.tmp.rglob("*") if p.is_file()}
    assert all(scan.out in p.parents for p in after - before)
    plan = scan.plan_json()
    import hashlib

    card_file = scan.cards / f"{SLUG}.yaml"
    assert plan["cards"][SLUG]["sha256"] == hashlib.sha256(card_file.read_bytes()).hexdigest()
    assert (scan.out / "step0.json").is_file()
    assert {s["study"] for s in plan["studies"]} == {
        f"pmid:{i}" for i in (AGREES_ID, UNVERIFIED_ID, FUKUDA_ID, GENERIC_ID, PAGE_ID)
    }
    assert (scan.out / "scan-context" / f"{SLUG}--pmid-{AGREES_ID}.md").is_file()


def test_the_context_holds_entry_items_carrier_step0_and_the_audit_rendering(scan: Scan):
    scan.plan()
    text = scan.context(AGREES_ID)
    assert f"id: pmid:{AGREES_ID}" in text and "case_definition: CCC" in text  # the study's entry
    assert "`core_claim`" in text and CARD_ONLY in text  # a card item citing it, under its target name
    assert "`level_reason[0]`" in text
    assert "Carrier of the level, a badge, the contested mark or a link: yes." in text
    assert "label: agrees" in text and "Canadian" in text  # step 0
    cfg = pipeline.Config(scan.out, scan.cards, cache_dir=scan.cache)
    record = "\n".join(fulltext_scan.render_record(cfg, f"pmid:{AGREES_ID}"))
    assert record in text  # the same text the audit context uses for a carrier, uncut
    assert ONLY_IN_FULLTEXT in text and "Not truncated" in text
    assert "Fictional reference with 999 patients" not in text  # the reference list is left out, as in the audit
    assert "Carrier of the level, a badge, the contested mark or a link: no." in scan.context(UNVERIFIED_ID)


def test_the_rendering_is_the_one_the_audit_context_uses(scan: Scan):
    scan.plan()
    cfg = pipeline.Config(scan.out, scan.cards, cache_dir=scan.cache)
    study = f"pmid:{AGREES_ID}"
    assert fulltext_scan.render_record(cfg, study) == pipeline._audit_record_lines(
        cfg, study, fulltext_scan.cache_loader(scan.cache), True
    )


def test_scan_plan_carrying_only_and_study_options(scan: Scan):
    assert scan.plan("--carrying-only") == 0
    assert {s["study"] for s in scan.plan_json()["studies"]} == {
        f"pmid:{i}" for i in (AGREES_ID, FUKUDA_ID, GENERIC_ID)
    }
    assert scan.plan("--study", f"pmid:{PAGE_ID}", f"pmid:{AGREES_ID}") == 0
    assert {s["study"] for s in scan.plan_json()["studies"]} == {f"pmid:{PAGE_ID}", f"pmid:{AGREES_ID}"}


def test_scan_plan_names_a_study_that_is_not_listed(scan: Scan, capsys):
    assert scan.plan("--study", f"pmid:{PDF_ID}") == 1
    assert "no listed study" in capsys.readouterr().err


# --- scan-record: validation -------------------------------------------------------------------------------------


def test_record_with_all_confirmed_flags_nothing_and_writes_no_request(scan: Scan):
    scan.plan()
    for s in scan.plan_json()["studies"]:
        scan.write_scan(s["study"].removeprefix("pmid:"))
    assert scan.record() == 0
    result = scan.result()
    assert result["flagged"] == {} and not (scan.out / "requests").exists()
    c = result["counts"]
    assert c["verdicts"]["confirmed"] > 0 and c["verdicts"]["differs"] == 0 and c["cards_flagged"] == 0
    text = scan.report()
    assert "step 0: agrees 1, differs 3, no_candidate 1" in text
    assert "quotes dropped: 0" in text and "files invalid: 0" in text and "cards flagged: 0" in text


def invalid_cases(scan: Scan) -> list[tuple[str, object, str]]:
    base_ok = json.loads(scan.write_scan(UNVERIFIED_ID).read_text(encoding="utf-8"))
    fields = base_ok["fields"]

    def with_field(name: str, value: object) -> dict:
        return {**base_ok, "fields": {**fields, name: value}}

    return [
        ("not json", "{not json", "not JSON"),
        ("wrong card", {**base_ok, "card": "another-card"}, "card is 'another-card'"),
        ("wrong study", {**base_ok, "study": "pmid:1"}, "study is 'pmid:1'"),
        (
            "missing key",
            {**base_ok, "fields": {k: v for k, v in fields.items() if k != "role"}},
            "lacks the key `role`",
        ),
        ("unknown verdict", with_field("role", {"verdict": "maybe", "quote": None, "note": None}), "unknown verdict"),
        (
            "differs without a quote",
            with_field("role", {"verdict": "differs", "quote": None, "note": "n"}),
            "needs a `quote`",
        ),
        (
            "not_cited on another field",
            with_field("role", {"verdict": "not_cited", "quote": None, "note": None}),
            "only for `carrying`",
        ),
    ]


def test_every_invalid_scan_file_is_reported_and_uses_no_verdict(scan: Scan, capsys):
    scan.plan()
    cases = invalid_cases(scan)
    for label, data, fragment in cases:
        scan.raw_scan(UNVERIFIED_ID, data if isinstance(data, str) else json.dumps(data))
        assert scan.record() == 0, label
        record = scan.record_of(UNVERIFIED_ID)
        assert record["invalid"] and any(fragment in p for p in record["invalid"]), (label, record["invalid"])
        assert record["scanned"] is False and record["verdicts"] == [] and record["flagged"] is False
        assert fragment in scan.report() and "files invalid: " in scan.report()
        assert scan.result()["flagged"] == {}


def test_not_cited_on_a_cited_study_is_invalid(scan: Scan):
    scan.plan()
    scan.write_scan(AGREES_ID, carrying={"verdict": "not_cited", "quote": None, "note": None})
    assert scan.record() == 0
    assert any("cited in a level" in p for p in scan.record_of(AGREES_ID)["invalid"])


def test_a_verdict_other_than_not_cited_on_an_uncited_study_is_invalid(scan: Scan):
    scan.plan()
    scan.write_scan(UNVERIFIED_ID, carrying={"verdict": "confirmed", "quote": None, "note": None})
    assert scan.record() == 0
    assert any("not_cited" in p for p in scan.record_of(UNVERIFIED_ID)["invalid"])


def test_a_target_the_context_does_not_list_is_invalid(scan: Scan):
    scan.plan()
    bad = {"verdict": "differs", "quote": ONLY_IN_FULLTEXT, "note": "n", "targets": ["level_reason[4]"]}
    scan.write_scan(AGREES_ID, carrying=bad)
    assert scan.record() == 0
    assert any("level_reason[4]" in p and "not listed" in p for p in scan.record_of(AGREES_ID)["invalid"])
    assert scan.result()["flagged"] == {}


def test_a_carrying_differs_needs_targets(scan: Scan):
    scan.plan()
    scan.write_scan(AGREES_ID, carrying={"verdict": "differs", "quote": ONLY_IN_FULLTEXT, "note": "n"})
    assert scan.record() == 0
    assert any("needs `targets`" in p for p in scan.record_of(AGREES_ID)["invalid"])


def test_a_stray_scan_file_is_reported_invalid(scan: Scan):
    scan.plan()
    (scan.out / "scan").mkdir()
    (scan.out / "scan" / "other.json").write_text("{}", encoding="utf-8")
    assert scan.record() == 0
    assert scan.result()["counts"]["files_invalid"] == 1


# --- scan-record: the quote check --------------------------------------------------------------------------------


def test_a_quote_found_only_in_the_card_text_of_the_context_is_dropped_and_reported(scan: Scan):
    scan.plan()
    assert CARD_ONLY in scan.context(AGREES_ID)
    scan.write_scan(AGREES_ID, finding=differs(CARD_ONLY))
    assert scan.record() == 0
    record = scan.record_of(AGREES_ID)
    assert record["verdicts"][0]["verdict"] == "confirmed" and all(v["field"] != "finding" for v in record["verdicts"])
    assert [d["field"] for d in record["dropped"]] == ["finding"]
    assert record["flagged"] is False and scan.result()["flagged"] == {}
    assert "quotes dropped: 1" in scan.report() and "not found word for word" in scan.report()
    assert not (scan.out / "requests").exists()  # its only differs was dropped: no request


def test_a_quote_that_differs_only_in_quotes_and_whitespace_is_kept(scan: Scan):
    scan.plan()
    curly = "The  median disease\nduration was nine years."
    scan.write_scan(UNVERIFIED_ID, finding=differs(curly))
    assert scan.record() == 0
    record = scan.record_of(UNVERIFIED_ID)
    assert record["dropped"] == [] and record["flagged"] is True
    assert scan.result()["flagged"] == {SLUG: [f"pmid:{UNVERIFIED_ID}"]}


def test_a_quote_with_curly_apostrophes_is_kept(scan: Scan):
    assert fulltext_scan.quote_in_fulltext("patients’ own", "the patients' own report")
    assert not fulltext_scan.quote_in_fulltext("a different sentence", "the patients' own report")
    assert not fulltext_scan.quote_in_fulltext("anything", None)


# --- scan-record: outputs ----------------------------------------------------------------------------------------


def flag_one(scan: Scan) -> None:
    scan.plan()
    scan.write_scan(UNVERIFIED_ID, case_definition=differs(FUKUDA_TEXT, "The full text names the Fukuda criteria."))
    scan.write_scan(
        AGREES_ID,
        carrying={
            "verdict": "adds",
            "quote": ONLY_IN_FULLTEXT,
            "note": "A duration bears on the reason.",
            "targets": ["level_reason[0]"],
        },
    )


def test_a_flagged_card_gets_a_request_that_loads_against_the_correction_path(scan: Scan, tmp_path: Path):
    flag_one(scan)
    assert scan.record() == 0
    request_path = scan.out / "requests" / SLUG / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["origin_kind"] == "fulltext_scan" and request["card"] == SLUG
    result_path = scan.out / "scan-result.json"
    import hashlib

    assert request["scan"] == {
        "result": str(result_path.resolve()),
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
    }
    targets = [i["target"] for i in request["items"]]
    assert targets == [f"studies[pmid:{UNVERIFIED_ID}].case_definition", "level_reason[0]"] or set(targets) == {
        f"studies[pmid:{UNVERIFIED_ID}].case_definition",
        "level_reason[0]",
    }
    assert all(ONLY_IN_FULLTEXT in i["problem"] or FUKUDA_TEXT in i["problem"] for i in request["items"])
    from me_atlas import card_correction

    run = tmp_path / "correction"
    run.mkdir()
    (run / "request.json").write_text(request_path.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = pipeline.Config(run, scan.cards, tmp_path / "drafts", scan.cache)
    loaded = card_correction.load_request(cfg, SLUG, cards.load_card(scan.cards / f"{SLUG}.yaml"))
    assert loaded.origin_kind == "fulltext_scan" and loaded.scan is not None


def test_the_counts_in_the_report_and_the_result(scan: Scan):
    flag_one(scan)
    scan.raw_scan(GENERIC_ID, "{not json")
    assert scan.record() == 0
    c = scan.result()["counts"]
    assert c["step0"] == {"agrees": 1, "differs": 3, "no_candidate": 1}
    assert c["verdicts"]["differs"] == 1 and c["verdicts"]["adds"] == 1
    assert c["files_invalid"] == 1 and c["cards_flagged"] == 1
    text = scan.report()
    assert "differs 1, adds 1" in text and "cards flagged: 1" in text and "## Flagged: " + SLUG in text
    assert ONLY_IN_FULLTEXT in text


def test_scan_record_without_a_plan_is_refused(tmp_path: Path, capsys):
    assert fulltext.main(["scan-record", "--out", str(tmp_path / "nothing")]) == 1
    assert "scan-plan" in capsys.readouterr().err


def test_a_scan_result_must_validate(scan: Scan):
    flag_one(scan)
    assert scan.record() == 0
    path = scan.out / "scan-result.json"
    assert fulltext_scan.flagged_studies(fulltext_scan.load_scan_result(path), SLUG) == {
        f"pmid:{UNVERIFIED_ID}": "fulltext_xml",
        f"pmid:{AGREES_ID}": "fulltext_xml",
    }
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cards"][SLUG]["studies"][f"pmid:{UNVERIFIED_ID}"]["verdicts"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(fulltext_scan.ScanResultError, match="no kept differs/adds"):
        fulltext_scan.load_scan_result(path)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(fulltext_scan.ScanResultError, match="not readable JSON"):
        fulltext_scan.load_scan_result(path)
    path.write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
    with pytest.raises(fulltext_scan.ScanResultError, match="lacks"):
        fulltext_scan.load_scan_result(path)


# --- the agent prompts -------------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / ".claude" / "agents"


def test_the_scanner_prompt_states_the_format_the_verdicts_and_its_limits():
    text = (AGENTS / "fulltext-scanner.md").read_text(encoding="utf-8")
    front = text.split("---")[1]
    assert "name: fulltext-scanner" in front and "model: sonnet" in front and "tools: Read, Write" in front
    for field in fulltext_scan.FIELDS:
        assert f"`{field}`" in text
    for word in ("confirmed", "differs", "adds", "not_cited", "targets", "quote", "note"):
        assert f"`{word}`" in text
    assert "Only the context file you were given" in text and "Only the scan file" in text
    assert "No treatment advice" in text and "You do not grade" in text
    assert "`not_cited`" in text and "cited in none of those" in text


def test_the_json_example_of_the_scanner_prompt_is_a_valid_scan_file():
    text = (AGENTS / "fulltext-scanner.md").read_text(encoding="utf-8")
    block = text.split("```json", 1)[1].split("```", 1)[0]
    data = json.loads(block)
    entry = {
        "card": data["card"],
        "study": data["study"],
        "cited_in_reason": True,
        "carrying_targets": ["level_reason[0]"],
    }
    assert fulltext_scan.validate_scan_file(data, entry) == []
    assert list(data["fields"]) == list(fulltext_scan.FIELDS)


def test_the_other_agents_gain_a_paragraph_scoped_to_the_scan_and_keep_their_limits():
    drafter = (AGENTS / "card-drafter.md").read_text(encoding="utf-8")
    reviewer = (AGENTS / "card-reviewer.md").read_text(encoding="utf-8")
    auditor = (AGENTS / "auditor.md").read_text(encoding="utf-8")
    for text in (drafter, reviewer, auditor):
        assert (
            "**A request from the full-text scan.**" in text
            and "nothing in this paragraph applies" in text
            or ("none of this paragraph applies" in text)
        )
    assert (
        "No `add_study`, no `add_paragraph`, no `add_link`, no `add_sentence`: a correction here removes or rewords"
        in drafter
    )
    assert "Add no number that the text did not already state" in drafter
    assert "A wording-only correction (free text only, no number, every answered finding classed `wording`)" in drafter
    assert "`accept_lower` is valid in form but is not applied in this path" in auditor
    assert "classify as strictly as the rule says and when in doubt use `decisive`" in reviewer
