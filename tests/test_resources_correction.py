"""One correction round of a rejected value: ``resources reliability --run NEW --correction-of OLD``. Offline."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from me_atlas import resources

DAY = "2026-11-18"
LATER = "2026-11-19"
MAIN_TEXT = (
    "The Fictional Biobank holds blood samples and questionnaire data. Access is granted by application. "
    "It covers people with ME/CFS. Researchers outside the Imaginary Institute can obtain access."
)


def q(value: str, quote: str) -> dict:
    return {"value": value, "quote": quote, "page": "main"}


def entry_draft(lid: str) -> dict:
    return {
        "id": lid,
        "include": True,
        "language": "en",
        "category": "data",
        "name": q("Fictional Biobank", "The Fictional Biobank holds"),
        "holds": [q("biospecimens", "holds blood samples")],
        "access": q("application", "Access is granted by application"),
        "covers": q("me_cfs", "It covers people with ME/CFS"),
    }


def exclusion_draft(lid: str) -> dict:
    return {
        "id": lid,
        "include": False,
        "reason": "no_outside_access",
        "quote": "Researchers outside the Imaginary Institute can obtain access",
        "page": "main",
    }


def review(lid: str, *rejected: str, finding: str = "The quote does not support the value.") -> dict:
    keys = resources.reviewable_keys(entry_draft(lid))
    values = {k: {"verdict": "accept"} for k in keys}
    for k in rejected:
        values[k] = {"verdict": "reject", "finding": f"{finding} ({k})"}
    return {"id": lid, "values": values}


def make_run(base: Path, name: str, drafts: dict, reviews: dict) -> Path:
    run = base / name
    run.mkdir(parents=True)
    context = {
        "url": "https://example.test/b",
        "access_url": None,
        "fetched": DAY,
        "pages": {"main": MAIN_TEXT},
    }
    for lid, draft in drafts.items():
        (run / f"context-{lid}.json").write_text(json.dumps({**context, "id": lid}), encoding="utf-8")
        (run / f"draft-{lid}.json").write_text(json.dumps(draft), encoding="utf-8")
    for lid, rv in reviews.items():
        (run / f"review-{lid}.json").write_text(json.dumps(rv), encoding="utf-8")
    return run


def old_run(base: Path) -> Path:
    """Three leads: a is rejected on access, name and covers, b is all accepted, c is an exclusion."""
    drafts = {"a-res": entry_draft("a-res"), "b-res": entry_draft("b-res"), "c-res": exclusion_draft("c-res")}
    reviews = {
        "a-res": review("a-res", "access", "name", "covers"),
        "b-res": review("b-res"),
        "c-res": {"id": "c-res", "verdict": "accept"},
    }
    return make_run(base, "old", drafts, reviews)


def new_run(base: Path, lead: str = "a-res", *, rejected: tuple[str, ...] = (), exclusion: bool = False) -> Path:
    draft = exclusion_draft(lead) if exclusion else entry_draft(lead)
    rv = {"id": lead, "verdict": "accept"} if exclusion else review(lead, *rejected)
    return make_run(base, "new", {lead: draft}, {lead: rv})


def record_of(old: Path) -> dict:
    result, problems = resources.reliability(old, DAY)
    assert problems == []
    return result


def setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    old = old_run(tmp_path)
    file = tmp_path / "rel.yaml"
    file.write_text(yaml.safe_dump(record_of(old), sort_keys=False), encoding="utf-8")
    return old, file, tmp_path


def correct(file: Path, new: Path, old: Path) -> int:
    return resources.main(
        ["--reliability-file", str(file), "reliability", "--run", str(new), "--correction-of", str(old)]
    )


def refused(tmp_path: Path, file: Path, new: Path, old: Path, capsys, text: str) -> None:
    before = file.read_bytes()
    assert correct(file, new, old) == 1
    assert file.read_bytes() == before  # nothing written
    assert text in capsys.readouterr().err


def test_an_accepted_correction_appends_an_item_and_leaves_the_record_as_it_was(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    before = yaml.safe_load(file.read_text(encoding="utf-8"))
    new = new_run(tmp_path, "a-res", rejected=("name",))
    assert correct(file, new, old) == 0
    after = yaml.safe_load(file.read_text(encoding="utf-8"))
    assert {k: v for k, v in after.items() if k != "corrections"} == before
    assert before["passed"] is False  # the first run: 3 rejects of 11 values
    (item,) = after["corrections"]
    assert set(item) == {"date", "run", "correction_of", "leads", "findings", "values", "entries"}
    assert item["run"] == new.as_posix() and item["correction_of"] == old.as_posix()
    assert item["leads"] == ["a-res"]
    assert item["findings"] == {
        "a-res": {
            "access": "The quote does not support the value. (access)",
            "covers": "The quote does not support the value. (covers)",
            "name": "The quote does not support the value. (name)",
        }
    }
    assert item["values"] == {"total": 5, "rejects": 1, "reject_rate": 0.2}
    assert item["entries"] == {"drafts": 1, "written": 0, "left_out": 1}
    assert "passed" not in item
    assert "CORRECTION: 1 reject(s) of 5 value(s)" in capsys.readouterr().out


def test_a_correction_never_sets_or_changes_the_gate(tmp_path):
    old, file, _ = setup(tmp_path)
    assert resources.load_reliability(file) is False
    assert correct(file, new_run(tmp_path), old) == 0  # every value accepted in the second round
    assert yaml.safe_load(file.read_text(encoding="utf-8"))["corrections"][0]["values"]["rejects"] == 0
    assert resources.load_reliability(file) is False


def test_a_second_correction_of_the_same_lead_is_refused(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    assert correct(file, new_run(tmp_path), old) == 0
    again = make_run(tmp_path, "again", {"a-res": entry_draft("a-res")}, {"a-res": review("a-res")})
    refused(tmp_path, file, again, old, capsys, "a-res: already corrected once")


def test_a_second_lead_may_be_corrected_in_its_own_round(tmp_path):
    old = tmp_path / "old"
    drafts = {"a-res": entry_draft("a-res"), "b-res": entry_draft("b-res")}
    make_run(tmp_path, "old", drafts, {"a-res": review("a-res", "name"), "b-res": review("b-res", "covers")})
    file = tmp_path / "rel.yaml"
    file.write_text(yaml.safe_dump(record_of(old), sort_keys=False), encoding="utf-8")
    assert correct(file, new_run(tmp_path, "a-res"), old) == 0
    second = make_run(tmp_path, "second", {"b-res": entry_draft("b-res")}, {"b-res": review("b-res")})
    assert correct(file, second, old) == 0
    assert [i["leads"] for i in yaml.safe_load(file.read_text(encoding="utf-8"))["corrections"]] == [
        ["a-res"],
        ["b-res"],
    ]


def test_refused_when_the_reliability_file_has_no_top_level_record(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    file.write_text(yaml.safe_dump({"corrections": []}), encoding="utf-8")
    refused(tmp_path, file, new_run(tmp_path), old, capsys, "no top-level record")


def test_refused_when_there_is_no_reliability_file(tmp_path, capsys):
    old = old_run(tmp_path)
    file = tmp_path / "none.yaml"
    assert correct(file, new_run(tmp_path), old) == 1
    assert not file.exists() and "no reliability file" in capsys.readouterr().err


def test_refused_when_old_is_not_the_run_of_the_record(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    other = tmp_path / "other"
    refused(tmp_path, file, new_run(tmp_path), other, capsys, "is not the run of the reliability record")


def test_refused_when_a_lead_has_no_review_in_old(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    new = new_run(tmp_path, "d-res")
    refused(tmp_path, file, new, old, capsys, "d-res: no review in the earlier run")


def test_refused_when_old_rejected_no_value_of_the_lead(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    new = new_run(tmp_path, "b-res")  # b-res was all accepted
    refused(tmp_path, file, new, old, capsys, "b-res: the earlier review rejected no value")


def test_refused_when_old_judged_the_lead_as_an_exclusion(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    new = new_run(tmp_path, "c-res")
    refused(tmp_path, file, new, old, capsys, "c-res: the earlier review is not a per-value entry review")


def test_refused_when_new_holds_an_exclusion_draft(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    new = new_run(tmp_path, "a-res", exclusion=True)
    refused(tmp_path, file, new, old, capsys, "a-res: an exclusion draft")


def test_refused_when_the_new_run_is_incomplete(tmp_path, capsys):
    old, file, _ = setup(tmp_path)
    new = make_run(tmp_path, "new", {"a-res": entry_draft("a-res")}, {})  # no review file
    refused(tmp_path, file, new, old, capsys, "the review file")


def test_the_plain_command_still_overwrites_and_drops_the_earlier_corrections(tmp_path):
    old, file, _ = setup(tmp_path)
    assert correct(file, new_run(tmp_path), old) == 0
    assert "corrections" in yaml.safe_load(file.read_text(encoding="utf-8"))
    fresh = make_run(tmp_path, "fresh", {"a-res": entry_draft("a-res")}, {"a-res": review("a-res")})
    assert resources.main(["--reliability-file", str(file), "reliability", "--run", str(fresh)]) == 0
    written = yaml.safe_load(file.read_text(encoding="utf-8"))
    assert set(written) == {"date", "run", "values", "entries", "exclusions", "passed"}
    assert written["run"] == fresh.as_posix() and written["passed"] is True
