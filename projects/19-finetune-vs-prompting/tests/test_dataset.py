"""Dataset builder: PII scrubbing, dedup, group split, leakage check, chat format."""

import json

import pytest

from finetune_lab.compare import DATA
from finetune_lab.corpus import Record, generate
from finetune_lab.dataset import (
    SPLITS,
    Example,
    LeakageError,
    build,
    find_leaks,
    fingerprint,
    validate_chat_file,
    write,
)
from finetune_lab.labels import SYSTEM_PROMPT_FT
from finetune_lab.pii import contains_pii, scrub


@pytest.fixture(scope="module")
def raw():
    return generate()


@pytest.fixture(scope="module")
def built(raw):
    return build(raw)


def test_no_planted_pii_value_survives_in_any_split(raw, tmp_path):
    splits, report = build(raw)
    write(splits, report, tmp_path)
    text = "".join((tmp_path / f"{s}.jsonl").read_text() for s in SPLITS)
    planted = {v for r in raw for v in r.pii}
    assert planted and not [v for v in planted if v in text]
    assert sum(report.pii_redactions.values()) > len(raw)


def test_scrub_handles_ocr_garbled_anchors_and_keeps_document_cues():
    text, counts = scrub(
        "Form W-2\nproposed lnsured Jordan Castellano\nSSN 512-44-9087\n"
        "Phone (555) 013-2231\nAccount 482019337162\nAddress 4410 Juniper Ln"
    )
    assert "Castellano" not in text and "9087" not in text and "Juniper" not in text
    assert set(counts) == {"NAME", "SSN", "PHONE", "ACCOUNT", "ADDRESS"}
    assert "Form W-2" in text and not contains_pii(text)


def test_duplicates_are_removed_before_splitting(raw, built):
    splits, report = built
    assert report.exact_duplicates > 0  # the generator re-uploads ~6% of documents
    fps = [e.fp for s in SPLITS for e in splits[s]]
    assert len(fps) == len(set(fps))


def test_rescanned_copy_has_the_same_fingerprint():
    a = "Pay stub\nGross pay $4,210.00\nNet pay $3,011.54"
    assert fingerprint(a) == fingerprint("  ".join(a.upper().split(" ")))
    assert fingerprint(a) == fingerprint(a.replace("l", "1").replace("4,210", "9,999"))


def test_conflicting_labels_for_one_document_drop_every_copy():
    recs = [
        Record(f"D-{i}", f"LN-{i}", lbl, "GIFT LETTER\nNo repayment expected", [])
        for i, lbl in enumerate(["gift_letter", "gift_letter", "pay_stub"])
    ]
    recs += generate(n_per_label=3, n_loans=12, seed=5)
    _, report = build(recs)
    assert report.label_conflicts == 3


def test_splits_share_no_loan_file_fingerprint_or_near_duplicate(built):
    splits, report = built
    assert not any(find_leaks(splits).values())
    loans = [{e.loan_id for e in splits[s]} for s in SPLITS]
    assert not (loans[0] & loans[1] or loans[0] & loans[2] or loans[1] & loans[2])
    assert set(report.leakage_dropped) == {"val", "test"}


def test_leak_detector_flags_a_near_duplicate_across_splits():
    text = (
        "Uniform Residential Appraisal Report Subject property Sales comparison approach "
        "Gross living area Neighborhood suburban stable Condition rating"
    )
    tr = Example("A", "LN-1", "appraisal", text, fingerprint(text))
    te = Example("B", "LN-2", "appraisal", text + " Site value", fingerprint(text + "x"))
    assert find_leaks({"train": [tr], "val": [], "test": [te]})["test"] == ["B"]


def test_build_refuses_to_write_when_leakage_cannot_be_filtered(monkeypatch, raw):
    import finetune_lab.dataset as ds

    monkeypatch.setattr(ds, "find_leaks", lambda splits: {"val": ["X"], "test": []})
    with pytest.raises(LeakageError):
        ds.build(raw)


def test_files_are_valid_chat_fine_tuning_format():
    for s in SPLITS:
        assert validate_chat_file(DATA / f"{s}.jsonl") == []
    first = json.loads((DATA / "train.jsonl").read_text().splitlines()[0])
    assert first["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT_FT}


def test_validator_rejects_bad_rows(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(
        '{"messages": [{"role": "user", "content": "x"}]}\n'
        '{"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": '
        '"SSN 512-44-9087"}, {"role": "assistant", "content": "w2"}]}\n'
    )
    problems = validate_chat_file(p)
    assert len(problems) == 2 and "PII" in problems[1]


def test_committed_data_is_reproducible_from_the_seed(tmp_path, built):
    splits, report = built
    write(splits, report, tmp_path)
    for name in (*[f"{s}.jsonl" for s in SPLITS], "manifest.json"):
        assert (tmp_path / name).read_bytes() == (DATA / name).read_bytes(), name
