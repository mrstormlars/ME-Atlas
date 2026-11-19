"""A founder-requested correction round: ``record-review`` and ``reliability`` with ``--founder-request``. Offline."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from me_atlas import resources

DAY = "2026-11-18"
LATER = "2026-11-19"
MAIN_TEXT = (
    "The Fictional Biobank holds blood samples and questionnaire data. Access is granted by application. "
    "It covers people with ME/CFS. Researchers outside the Imaginary Institute can obtain access. "
    "Genotype data are also held. The Fictional Biobank Network is the long name."
)


def q(value: str, quote: str) -> dict:
    return {"value": value, "quote": quote, "page": "main"}


def entry_draft(lid: str, *, name: str = "Fictional Biobank", holds=(("biospecimens", "holds blood samples"),)) -> dict:
    return {
        "id": lid,
        "include": True,
        "language": "en",
        "category": "data",
        "name": q(name, "The Fictional Biobank holds" if name == "Fictional Biobank" else name),
        "holds": [q(v, quote) for v, quote in holds],
        "access": q("application", "Access is granted by application"),
        "covers": q("me_cfs", "It covers people with ME/CFS"),
    }


def review_of(draft: dict, *rejected: str) -> dict:
    values = {k: {"verdict": "accept"} for k in resources.reviewable_keys(draft)}
    for k in rejected:
        values[k] = {"verdict": "reject", "finding": f"No support. ({k})"}
    return {"id": draft["id"], "values": values}


def make_run(base: Path, name: str, drafts: dict, reviews: dict, text: str = MAIN_TEXT) -> Path:
    run = base / name
    run.mkdir(parents=True)
    context = {"url": "https://example.test/b", "access_url": None, "fetched": LATER, "pages": {"main": text}}
    for lid, draft in drafts.items():
        (run / f"context-{lid}.json").write_text(json.dumps({**context, "id": lid}), encoding="utf-8")
        (run / f"draft-{lid}.json").write_text(json.dumps(draft), encoding="utf-8")
    for lid, rv in reviews.items():
        (run / f"review-{lid}.json").write_text(json.dumps(rv), encoding="utf-8")
    return run


def published_file(base: Path, lids=("a-res",), text: str = MAIN_TEXT) -> Path:
    """The data file as an earlier run left it: name 'Old Name', holds biospecimens and questionnaires."""
    entries = []
    for lid in lids:
        draft = entry_draft(
            lid,
            holds=(("biospecimens", "holds blood samples"), ("questionnaires", "questionnaire data")),
        )
        draft["name"] = q("Old Name", "The Fictional Biobank holds")
        context = {"url": "https://example.test/b", "access_url": None, "fetched": DAY, "pages": {"main": text}}
        entries.append(resources.build_entry(context, draft))
    file = base / "resources.yaml"
    file.write_text(resources.dump_data({"checked": DAY, "entries": entries}), encoding="utf-8")
    return file


def request_file(base: Path, request: dict) -> Path:
    path = base / "founder-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def new_run(base: Path, draft: dict | None = None, *rejected: str) -> Path:
    draft = draft or entry_draft("a-res")
    return make_run(base, "new", {draft["id"]: draft}, {draft["id"]: review_of(draft, *rejected)})


def record(data_file: Path, run: Path, request: Path) -> int:
    return resources.main(
        ["--data-file", str(data_file), "record-review", "--run", str(run), "--founder-request", str(request)]
    )


def entry_of(data_file: Path, lid: str = "a-res") -> dict:
    return {e["id"]: e for e in yaml.safe_load(data_file.read_text(encoding="utf-8"))["entries"]}[lid]


def refused(data_file: Path, run: Path, request: Path, capsys, text: str) -> None:
    before = data_file.read_bytes()
    assert record(data_file, run, request) == 1
    assert data_file.read_bytes() == before
    assert text in capsys.readouterr().err


def test_an_accepted_name_replaces_the_published_name(tmp_path):
    data = published_file(tmp_path)
    new = new_run(tmp_path, entry_draft("a-res", name="The Fictional Biobank Network"))
    assert record(data, new, request_file(tmp_path, {"a-res": "The name is too short."})) == 0
    entry = entry_of(data)
    assert entry["name"] == "The Fictional Biobank Network"
    assert entry["quotes"]["name"]["quote"] == "The Fictional Biobank Network"
    assert entry["checked"] == DAY and entry["text_hash"] == {"main": resources.text_hash(MAIN_TEXT)}


def test_a_rejected_name_keeps_the_published_name(tmp_path):
    data = published_file(tmp_path)
    new = new_run(tmp_path, entry_draft("a-res", name="The Fictional Biobank Network"), "name")
    assert record(data, new, request_file(tmp_path, {"a-res": "x"})) == 0
    entry = entry_of(data)
    assert entry["name"] == "Old Name"
    assert entry["quotes"]["name"]["quote"] == "The Fictional Biobank holds"


def test_language_follows_an_accepted_name_and_stays_when_the_name_is_rejected(tmp_path):
    data = published_file(tmp_path)  # the published entry is "en"
    draft = entry_draft("a-res", name="The Fictional Biobank Network")
    draft["language"] = "nb"
    assert record(data, new_run(tmp_path, draft), request_file(tmp_path, {"a-res": "x"})) == 0
    assert entry_of(data)["language"] == "nb"
    (tmp_path / "second").mkdir()
    data2 = published_file(tmp_path / "second")
    rejected = make_run(tmp_path / "second", "new", {"a-res": draft}, {"a-res": review_of(draft, "name")})
    assert record(data2, rejected, request_file(tmp_path / "second", {"a-res": "x"})) == 0
    assert entry_of(data2)["language"] == "en"


def test_an_accepted_new_holds_value_is_added(tmp_path):
    data = published_file(tmp_path)
    draft = entry_draft("a-res", holds=(("genotypes", "Genotype data are also held"),))
    assert record(data, new_run(tmp_path, draft), request_file(tmp_path, {"a-res": "x"})) == 0
    entry = entry_of(data)
    assert entry["holds"] == ["biospecimens", "genotypes", "questionnaires"]
    assert entry["quotes"]["holds"]["genotypes"]["quote"] == "Genotype data are also held"


def test_a_rejected_new_holds_value_is_not_added_and_published_holds_are_kept(tmp_path):
    data = published_file(tmp_path)
    draft = entry_draft("a-res", holds=(("genotypes", "Genotype data are also held"),))
    assert record(data, new_run(tmp_path, draft, "holds.genotypes"), request_file(tmp_path, {"a-res": "x"})) == 0
    assert entry_of(data)["holds"] == ["biospecimens", "questionnaires"]


def test_a_holds_value_the_new_draft_leaves_out_is_kept(tmp_path):
    data = published_file(tmp_path)  # the new draft holds only biospecimens
    assert record(data, new_run(tmp_path), request_file(tmp_path, {"a-res": "x"})) == 0
    entry = entry_of(data)
    assert entry["holds"] == ["biospecimens", "questionnaires"]
    assert entry["quotes"]["holds"]["questionnaires"]["quote"] == "questionnaire data"


def test_a_value_accepted_in_both_takes_the_new_quote(tmp_path):
    data = published_file(tmp_path)
    draft = entry_draft("a-res", holds=(("biospecimens", "blood samples"),))
    assert record(data, new_run(tmp_path, draft), request_file(tmp_path, {"a-res": "x"})) == 0
    assert entry_of(data)["quotes"]["holds"]["biospecimens"]["quote"] == "blood samples"


def test_a_rejected_access_keeps_the_published_access_and_the_entry_is_not_left_out(tmp_path):
    data = published_file(tmp_path)
    draft = entry_draft("a-res")
    draft["access"] = q("registration", "Access is granted by application")
    assert record(data, new_run(tmp_path, draft, "access"), request_file(tmp_path, {"a-res": "x"})) == 0
    entry = entry_of(data)
    assert entry["access"] == "application"  # the plain record-review would leave a data entry out here
    assert entry["id"] == "a-res"


def test_the_result_passes_the_checks_and_the_other_entries_stay(tmp_path):
    data = published_file(tmp_path, ("a-res", "b-res"))
    before_b = entry_of(data, "b-res")
    new = new_run(tmp_path, entry_draft("a-res", name="The Fictional Biobank Network"))
    assert record(data, new, request_file(tmp_path, {"a-res": "x"})) == 0
    parsed = yaml.safe_load(data.read_text(encoding="utf-8"))
    assert resources.check_data(parsed) == []
    assert entry_of(data, "b-res") == before_b
    assert entry_of(data)["name"] == "The Fictional Biobank Network"


def test_refused_when_a_lead_of_the_run_is_not_in_the_request(tmp_path, capsys):
    data = published_file(tmp_path, ("a-res", "b-res"))
    refused(
        data,
        new_run(tmp_path),
        request_file(tmp_path, {"b-res": "x"}),
        capsys,
        "in the founder request but not in the run",
    )


def test_refused_when_the_run_has_a_lead_that_is_not_requested(tmp_path, capsys):
    data = published_file(tmp_path, ("a-res", "b-res"))
    other = entry_draft("b-res")
    new = make_run(
        tmp_path,
        "new",
        {"a-res": entry_draft("a-res"), "b-res": other},
        {"a-res": review_of(entry_draft("a-res")), "b-res": review_of(other)},
    )
    refused(data, new, request_file(tmp_path, {"a-res": "x"}), capsys, "b-res: not in the founder request")


def test_refused_when_a_lead_has_no_published_entry(tmp_path, capsys):
    data = published_file(tmp_path, ("b-res",))
    new = new_run(tmp_path)
    refused(
        data, new, request_file(tmp_path, {"a-res": "x"}), capsys, "a-res: the request names a lead with no published"
    )


def test_refused_when_the_run_holds_an_exclusion_draft(tmp_path, capsys):
    data = published_file(tmp_path)
    ex = {
        "id": "a-res",
        "include": False,
        "reason": "no_outside_access",
        "quote": "Researchers outside the Imaginary Institute can obtain access",
        "page": "main",
    }
    new = make_run(tmp_path, "new", {"a-res": ex}, {"a-res": {"id": "a-res", "verdict": "accept"}})
    refused(data, new, request_file(tmp_path, {"a-res": "x"}), capsys, "a-res: an exclusion draft")


def test_refused_when_the_stored_pages_changed(tmp_path, capsys):
    data = published_file(tmp_path)
    draft = entry_draft("a-res")
    new = make_run(tmp_path, "new", {"a-res": draft}, {"a-res": review_of(draft)}, text=MAIN_TEXT + " More text.")
    refused(data, new, request_file(tmp_path, {"a-res": "x"}), capsys, "differ from the published entry's text_hash")


def test_refused_for_a_bad_request_file(tmp_path, capsys):
    data = published_file(tmp_path)
    new = new_run(tmp_path)
    for body, text in (
        ({"a-res": ""}, "a non-empty string"),
        ({"a-res": 5}, "a non-empty string"),
        ({}, "non-empty object"),
        (["a-res"], "non-empty object"),
    ):
        refused(data, new, request_file(tmp_path, body), capsys, text)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    refused(data, new, bad, capsys, "cannot read the founder request")
    refused(data, new, tmp_path / "missing.json", capsys, "no founder request file")


def test_without_the_option_record_review_is_the_plain_one(tmp_path):
    data = published_file(tmp_path)
    new = new_run(tmp_path, entry_draft("a-res", name="The Fictional Biobank Network"))
    assert resources.main(["--data-file", str(data), "record-review", "--run", str(new)]) == 0
    entry = entry_of(data)
    assert entry["holds"] == ["biospecimens"]  # replaced as a whole, not merged


# --- reliability ---------------------------------------------------------------------------------------------------


def rel_setup(tmp_path: Path) -> Path:
    first = make_run(
        tmp_path,
        "first",
        {"a-res": entry_draft("a-res")},
        {"a-res": review_of(entry_draft("a-res"), "name")},
    )
    result, problems = resources.reliability(first, DAY)
    assert problems == []
    file = tmp_path / "rel.yaml"
    file.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
    return file


def founder(file: Path, data: Path, run: Path, request: Path, *extra: str) -> int:
    return resources.main(
        ["--reliability-file", str(file), "--data-file", str(data), "reliability", "--run", str(run)]
        + ["--founder-request", str(request), *extra]
    )


def test_a_founder_item_has_the_shape_and_the_numbers_and_leaves_the_record_alone(tmp_path, capsys):
    file = rel_setup(tmp_path)
    data = published_file(tmp_path)
    before = yaml.safe_load(file.read_text(encoding="utf-8"))
    draft = entry_draft("a-res", name="The Fictional Biobank Network")
    new = new_run(tmp_path, draft, "holds.biospecimens")
    assert founder(file, data, new, request_file(tmp_path, {"a-res": "Name too short."})) == 0
    after = yaml.safe_load(file.read_text(encoding="utf-8"))
    assert {k: v for k, v in after.items() if k != "corrections"} == before
    (item,) = after["corrections"]
    assert set(item) == {"date", "run", "kind", "leads", "request", "values", "entries"}
    assert item["kind"] == "founder_request" and item["run"] == new.as_posix()
    assert item["leads"] == ["a-res"] and item["request"] == {"a-res": "Name too short."}
    assert item["values"] == {"total": 5, "rejects": 1, "reject_rate": 0.2}
    assert item["entries"] == {"drafts": 1, "written": 1}  # the name changes
    assert "passed" not in item
    assert "FOUNDER REQUEST: 1 reject(s) of 5 value(s)" in capsys.readouterr().out


def test_written_is_zero_when_the_merge_changes_nothing(tmp_path):
    file = rel_setup(tmp_path)
    data = published_file(tmp_path)
    draft = entry_draft("a-res", name="Old Name")
    draft["name"] = q("Old Name", "The Fictional Biobank holds")
    new = new_run(tmp_path, draft, "holds.biospecimens")
    assert founder(file, data, new, request_file(tmp_path, {"a-res": "x"})) == 0
    # the name and the other values are the published ones and biospecimens is rejected: nothing changes
    assert yaml.safe_load(file.read_text(encoding="utf-8"))["corrections"][0]["entries"]["written"] == 0


def reliability_refused(file, data, run, request, capsys, text, *extra):
    before = file.read_bytes()
    assert founder(file, data, run, request, *extra) == 1
    assert file.read_bytes() == before
    assert text in capsys.readouterr().err


def test_reliability_refused_without_a_top_level_record(tmp_path, capsys):
    file = rel_setup(tmp_path)
    file.write_text(yaml.safe_dump({"corrections": []}), encoding="utf-8")
    data = published_file(tmp_path)
    reliability_refused(
        file, data, new_run(tmp_path), request_file(tmp_path, {"a-res": "x"}), capsys, "no top-level record"
    )


def test_reliability_refused_without_a_reliability_file(tmp_path, capsys):
    data = published_file(tmp_path)
    file = tmp_path / "none.yaml"
    assert founder(file, data, new_run(tmp_path), request_file(tmp_path, {"a-res": "x"})) == 1
    assert not file.exists() and "no reliability file" in capsys.readouterr().err


def test_reliability_refused_for_an_exclusion_draft(tmp_path, capsys):
    file = rel_setup(tmp_path)
    data = published_file(tmp_path)
    ex = {
        "id": "a-res",
        "include": False,
        "reason": "no_outside_access",
        "quote": "Researchers outside",
        "page": "main",
    }
    new = make_run(tmp_path, "new", {"a-res": ex}, {"a-res": {"id": "a-res", "verdict": "accept"}})
    reliability_refused(file, data, new, request_file(tmp_path, {"a-res": "x"}), capsys, "an exclusion draft")


def test_reliability_refused_when_the_request_does_not_match_the_run(tmp_path, capsys):
    file = rel_setup(tmp_path)
    data = published_file(tmp_path, ("a-res", "b-res"))
    new = new_run(tmp_path)
    reliability_refused(
        file, data, new, request_file(tmp_path, {"b-res": "x"}), capsys, "a-res: not in the founder request"
    )
    reliability_refused(
        file,
        data,
        new,
        request_file(tmp_path, {"a-res": "x", "b-res": "y"}),
        capsys,
        "b-res: in the founder request but not in the run",
    )
    reliability_refused(
        file,
        data,
        new,
        request_file(tmp_path, {"a-res": "x", "c-res": "y"}),
        capsys,
        "c-res: the request names a lead with no published",
    )


def test_reliability_refused_with_both_options(tmp_path, capsys):
    file = rel_setup(tmp_path)
    data = published_file(tmp_path)
    old = tmp_path / "first"
    reliability_refused(
        file,
        data,
        new_run(tmp_path),
        request_file(tmp_path, {"a-res": "x"}),
        capsys,
        "cannot be used together",
        "--correction-of",
        str(old),
    )
