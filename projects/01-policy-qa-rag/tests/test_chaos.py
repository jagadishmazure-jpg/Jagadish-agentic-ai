"""Chaos tests driven by doctrine.yaml: each fault must produce the declared exit."""

from pathlib import Path

import pytest

from policy_qa.eval_suite import CHAOS_CHECKS, chaos_scenario
from shared.chaos import assert_exit, run_scenario
from shared.doctrine import load_card

CARD = load_card(Path(__file__).resolve().parents[1] / "doctrine.yaml")


@pytest.mark.parametrize("sc", CARD.chaos, ids=lambda s: s.fault)
def test_fault_takes_declared_exit(sc):
    result = run_scenario(sc.fault, chaos_scenario)
    assert_exit(result, sc.node, sc.exit)
    assert CHAOS_CHECKS[sc.fault](result), sc.invariant
