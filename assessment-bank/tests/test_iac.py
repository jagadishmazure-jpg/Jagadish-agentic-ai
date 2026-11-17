"""Terraform and Bicep describe the same assessment-bank shape."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TF = (ROOT / "infra" / "terraform" / "main.tf").read_text()
BICEP = (ROOT / "infra" / "bicep" / "main.bicep").read_text()


def test_both_tools_enable_entra_cosmos_and_scale_to_zero():
    assert "EnableServerless" in TF and "EnableServerless" in BICEP
    assert re.search(r"local_authentication_enabled\s+=\s+false", TF)
    assert "disableLocalAuth: true" in BICEP
    assert "/learnerId" in TF and "/learnerId" in BICEP
    assert 'value = "entra"' in TF
    assert "value: 'entra'" in BICEP
    assert "min_replicas" in TF and "minReplicas: 0" in BICEP
    assert "ASSESSMENT_STORE" in TF and "ASSESSMENT_STORE" in BICEP
    assert "ciamlogin.com" in TF and "ciamlogin.com" in BICEP
