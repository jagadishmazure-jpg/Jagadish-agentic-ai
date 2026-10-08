"""Static parity checks on the IaC twins (no Azure calls): private networking, alerts, Defender."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BICEP = ROOT / "infra/bicep"
TF = ROOT / "infra/terraform"
NSG_ASSOC = "azurerm_subnet_network_security_group_association"


def _default(variables: str, name: str) -> str:
    return re.search(rf'variable "{name}" \{{.*?default\s+= (\S+)', variables, re.S).group(1)


def test_foundry_and_key_vault_public_access_follow_private_networking():
    main_b, main_t = (BICEP / "main.bicep").read_text(), (TF / "main.tf").read_text()
    assert "param privateNetworking bool = false" in main_b  # public stays the cheap default
    assert "publicNetworkAccess: 'Enabled'" not in main_b
    assert main_b.count("publicNetworkAccess: publicAccess") == 2
    assert main_t.count("public_network_access_enabled = !var.private_networking") == 2
    assert _default((TF / "variables.tf").read_text(), "private_networking") == "false"
    pe_b = set(re.findall(r"\{ name: '([a-z]+)', id: [a-z]+\.id, group:", main_b))
    pe_block = main_t.split('module "private_endpoint"')[1]
    pe_t = set(re.findall(r"^\s+([a-z]+)\s+= \{ id = module\.", pe_block, re.M))
    assert pe_b == pe_t == {"foundry", "keyvault"}
    net_b = (BICEP / "modules/network.bicep").read_text()
    assert net_b.count("networkSecurityGroup: { id: nsg.id }") == 2
    assert (TF / "modules/network/main.tf").read_text().count(NSG_ASSOC) == 2


def test_alerts_diagnostics_and_defender_match_in_both_tools():
    main_b, main_t = (BICEP / "main.bicep").read_text(), (TF / "main.tf").read_text()
    alerts_t = main_t.split('module "alerts"')[1].split('module "defender"')[0]
    rule = r"\{ name: '([a-z0-9-]+)', (?:scope: \w+\.id, namespace|query):"
    names_b = set(re.findall(rule, main_b))
    names_t = set(re.findall(r"^\s+([a-z0-9-]+)\s+= \{ (?:scope|query) =", alerts_t, re.M))
    assert names_b == names_t and len(names_b) == 6, (names_b, names_t)
    diag_b = set(re.findall(r"name: 'diag-to-law', scope: (\w+)", main_b))
    diag_block = alerts_t.split("diagnostic_targets")[1]
    diag_t = set(re.findall(r"^\s+([a-z]+)\s+= module\.", diag_block, re.M))
    assert diag_b == {"foundry", "kv", "acr"} and diag_t == {"foundry", "keyvault", "registry"}
    assert "param enableAlerts bool = true" in main_b
    assert "param enableDefender bool = false" in main_b
    variables = (TF / "variables.tf").read_text()
    assert _default(variables, "enable_alerts") == "true"
    assert _default(variables, "enable_defender") == "false"
    assert "scope: subscription()" in main_b  # Defender pricings are subscription-wide
