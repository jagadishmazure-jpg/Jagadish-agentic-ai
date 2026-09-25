"""Offline fine-tune, comparison through the eval harness, promotion gate, registry."""

import json

import pytest

from finetune_lab.compare import (
    COMPARISON,
    README,
    classification_metrics,
    evaluate,
    readme_with_table,
    run_comparison,
)
from finetune_lab.labels import LABELS, SYSTEM_PROMPT_BASELINE
from finetune_lab.registry import ArtifactIntegrityError, ModelRegistry, PromotionRefusedError
from finetune_lab.trainer import LinearTextModel, artifact_sha256, train


@pytest.fixture(scope="module")
def comparison():
    return run_comparison()


def test_training_is_fast_and_deterministic(splits):
    a, b = train(splits["train"]), train(splits["train"])
    assert a.seconds < 30 and a.n_features > 500
    assert artifact_sha256(a.model.to_json()) == artifact_sha256(b.model.to_json())


def test_artifact_round_trips_through_json_without_pickle(splits):
    m = train(splits["train"]).model
    again = LinearTextModel.from_json(json.loads(json.dumps(m.to_json())))
    text = splits["test"][0][0]
    assert again.predict(text)[0] == m.predict(text)[0]


def test_fine_tuned_beats_prompted_baseline_and_is_promoted(comparison):
    report, registry = comparison
    val = report["results"]["val"]
    assert val["finetuned"]["macro_f1"] > val["baseline"]["macro_f1"]
    assert report["gate"]["passed"] and registry.champion.kind == "finetuned"
    # the fine-tuned prompt is ~10x shorter: the token proxy for cost per call
    assert val["finetuned"]["input_tokens_per_call"] < val["baseline"]["input_tokens_per_call"]


def test_weak_candidate_is_refused_and_champion_kept(splits):
    reg = ModelRegistry()
    base = reg.register_prompt(SYSTEM_PROMPT_BASELINE, "mock")
    reg.record_metrics(base.version, "val", {"accuracy": 0.64, "macro_f1": 0.74})
    reg.promote(base.version)
    weak = train(splits["train"][::40], min_df=1).model  # ~11 examples for 10 labels
    cand = reg.register_finetuned(weak, "sha")
    preds = [weak.predict(t)[0] for t, _ in splits["val"]]
    reg.record_metrics(
        cand.version, "val", classification_metrics([y for _, y in splits["val"]], preds)
    )
    with pytest.raises(PromotionRefusedError) as exc:
        reg.promote(cand.version)
    assert "macro_f1" in str(exc.value)
    assert reg.champion.version == base.version and reg.entries[cand.version].stage == "rejected"


def test_gate_blocks_a_per_label_regression_and_bad_training_data(splits):
    reg = ModelRegistry()
    base = reg.register_prompt("p", "mock")
    per = dict.fromkeys(LABELS, 0.8)
    reg.record_metrics(base.version, "val", {"accuracy": 0.8, "macro_f1": 0.8, "per_class_f1": per})
    reg.promote(base.version)
    cand = reg.register_finetuned(train(splits["train"]).model, "sha", dataset_checks_passed=False)
    worse = {**per, "gift_letter": 0.5}
    reg.record_metrics(
        cand.version, "val", {"accuracy": 0.9, "macro_f1": 0.9, "per_class_f1": worse}
    )
    problems = reg.gate(cand.version)
    assert any("gift_letter" in p for p in problems)
    assert any("PII/leakage" in p for p in problems)


def test_rollback_restores_previous_champion_and_persists(tmp_path, splits):
    reg = ModelRegistry(tmp_path)
    base = reg.register_prompt(SYSTEM_PROMPT_BASELINE, "mock")
    reg.record_metrics(base.version, "val", {"accuracy": 0.5, "macro_f1": 0.5})
    reg.promote(base.version)
    ft = reg.register_finetuned(train(splits["train"]).model, "sha")
    reg.record_metrics(ft.version, "val", {"accuracy": 0.9, "macro_f1": 0.9})
    reg.promote(ft.version)
    reg.rollback("drift")
    reloaded = ModelRegistry(tmp_path)
    assert reloaded.champion.version == base.version
    assert reloaded.entries[ft.version].stage == "archived"
    assert [e["event"] for e in reloaded.events][-1] == "rolled_back"
    with pytest.raises(RuntimeError):
        reloaded.rollback("again")  # nothing older than the first champion


def test_tampered_artifact_is_refused(tmp_path, splits):
    reg = ModelRegistry(tmp_path)
    ft = reg.register_finetuned(train(splits["train"]).model, "sha")
    path = tmp_path / "artifacts" / f"{ft.version}.json"
    art = json.loads(path.read_text())
    art["intercept"][0] += 5.0
    path.write_text(json.dumps(art))
    with pytest.raises(ArtifactIntegrityError):
        ModelRegistry(tmp_path).classifier(ft.version)


def test_committed_results_match_a_fresh_run(comparison):
    report, _ = comparison
    committed = json.loads(COMPARISON.read_text())
    for split in ("val", "test"):
        for variant in ("baseline", "finetuned"):
            fresh, old = report["results"][split][variant], committed["results"][split][variant]
            assert abs(fresh["accuracy"] - old["accuracy"]) <= 0.02
            assert abs(fresh["macro_f1"] - old["macro_f1"]) <= 0.02
    assert committed["gate"]["passed"] is True


def test_readme_results_table_is_rendered_from_committed_comparison():
    readme = README.read_text()
    assert readme == readme_with_table(readme, json.loads(COMPARISON.read_text()))


def test_an_unavailable_candidate_scores_as_errors_and_is_not_promoted():
    class Down:
        kind, version = "finetuned", "ft-down"

        def predict(self, text):
            raise ConnectionError("deployment down")

    m = evaluate(Down(), [("Form W-2 Wage and Tax Statement", "w2")] * 3, "val")
    assert m["accuracy"] == 0.0 and m["macro_f1"] == 0.0 and m["input_tokens_per_call"] == 0
