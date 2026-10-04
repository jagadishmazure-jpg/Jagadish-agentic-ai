"""Print Markdown sections of a project doc straight from its ``doctrine.yaml``.

Project READMEs paste these with ``<!-- output-md: python scripts/doc_tables.py 03 playbook -->``
markers, and ``scripts/render_docs.py --check`` fails CI when a card changes and the README does
not. So the failure playbook, chaos table, stop conditions and thresholds a reader sees are the
ones the promotion gate enforces.

    python scripts/doc_tables.py 03 playbook     # one table
    python scripts/doc_tables.py 03 all          # every section, for a quick look
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

AZURE_BY_KIND = {
    "mcp": "MCP server on Azure Container Apps (or Azure Functions), published through Azure API Management; called with the tool identity's managed identity",
    "api": "REST API fronted by Azure API Management (rate limits, JWT validation), called with a managed identity",
    "document_store": "Azure Blob Storage or SharePoint content indexed by Azure AI Search, labelled in Microsoft Purview",
    "semantic_model": "Microsoft Fabric semantic model or SQL endpoint, read through a governed MCP or XMLA endpoint",
    "event_stream": "Azure Event Hubs (consumer groups, checkpoints in Blob Storage)",
}


def project_dir(key: str) -> Path:
    hits = sorted((ROOT / "projects").glob(f"{key}*"))
    if not hits:
        raise SystemExit(f"no project matches {key}")
    return hits[0]


def card(pd: Path) -> dict:
    return yaml.safe_load((pd / "doctrine.yaml").read_text())


def esc(v: object) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def scores(pd: Path) -> dict:
    p = pd / "evals" / "scores.json"
    return json.loads(p.read_text()) if p.exists() else {}


def s_steps(pd: Path, c: dict) -> str:
    lines = [
        f"{i}. **`{r['node']}`**: {r['success']}." for i, r in enumerate(c["failure_playbook"], 1)
    ]
    return "\n".join(lines)


def s_planes(pd: Path, c: dict) -> str:
    return table(
        ["Plane", "What this project depends on"], [[k.title(), v] for k, v in c["planes"].items()]
    )


def s_sor(pd: Path, c: dict) -> str:
    rows = [
        [s["name"], s["kind"], f"`{s['contract']}`", s["access"]] for s in c["systems_of_record"]
    ]
    return table(["System of record", "Kind", "Contract", "Access"], rows)


def s_knowledge(pd: Path, c: dict) -> str:
    corpora = (c.get("knowledge") or {}).get("corpora") or []
    if not corpora:
        return (
            "_No retrieval corpus (by design): "
            + esc(
                (c.get("knowledge") or {}).get(
                    "justification", "decisions come from systems of record"
                )
            )
            + "_"
        )
    rows = [[k["name"], k["owner"], k["acl"], k["temporal"], k["sensitivity"]] for k in corpora]
    return table(["Corpus", "Owner", "ACL", "Temporal validity", "Sensitivity"], rows)


def s_identities(pd: Path, c: dict) -> str:
    rows = [
        [f"`{i['identity']}`", ", ".join(f"`{t}`" for t in i["allow"])]
        for i in c.get("identities", [])
    ]
    return table(["Tool identity", "Allowed tools (gateway allow-list)"], rows)


def s_stop(pd: Path, c: dict) -> str:
    return "\n".join(f"- {s}" for s in c["stop_conditions"])


def s_playbook(pd: Path, c: dict) -> str:
    keys = ["success", "retry", "compensate", "degrade", "escalate"]
    rows = [[f"`{r['node']}`", *(r[k] for k in keys)] for r in c["failure_playbook"]]
    return table(["Node", "Success", "Retry", "Compensate", "Degrade", "Escalate"], rows)


def s_chaos(pd: Path, c: dict) -> str:
    rows = [
        [f"`{r['fault']}`", f"`{r['node']}`", f"**{r['exit']}**", r["invariant"]]
        for r in c["chaos"]
    ]
    return table(
        ["Injected fault (`CHAOS_FAULTS`)", "Node", "Expected exit", "Invariant asserted"], rows
    )


def s_thresholds(pd: Path, c: dict) -> str:
    sc = scores(pd).get("metrics", scores(pd))
    rows = []
    for k, v in c["eval"]["thresholds"].items():
        cur = sc.get(k)
        rows.append(
            [
                f"`{k}`",
                f"`{v}`",
                "n/a" if cur is None else (f"{cur:.5f}" if k == "cost_per_task" else f"{cur:.2f}"),
            ]
        )
    return table(["Metric", "Threshold (doctrine.yaml)", "Current (evals/scores.json)"], rows)


def s_kpis(pd: Path, c: dict) -> str:
    return table(
        ["KPI", "Target", "How it is measured"],
        [[k["name"], k["target"], k["measure"]] for k in c["kpis"]],
    )


def s_azure(pd: Path, c: dict) -> str:
    rows = [
        [
            "Model calls",
            "Azure OpenAI in Microsoft Foundry, keyless through `DefaultAzureCredential` (`shared/llm.py`), with a fallback deployment behind a circuit breaker",
        ],
        [
            "Agent runtime",
            f"Azure Container Apps (the `{c['graph']}` graph runs inside the portfolio API image); LangGraph checkpoints in Azure Database for PostgreSQL",
        ],
    ]
    for k in (c.get("knowledge") or {}).get("corpora") or []:
        rows.append(
            [
                f"Corpus `{k['name']}`",
                f"Azure AI Search index with security-trimming filters for the ACL and `valid_from`/`valid_to` fields; sensitivity `{k['sensitivity']}` as a Microsoft Purview label",
            ]
        )
    for s in c["systems_of_record"]:
        rows.append([s["name"], AZURE_BY_KIND.get(s["kind"], s["kind"])])
    rows += [
        [
            "Tool identities",
            "One user-assigned managed identity per row of the identity table, scoped with Azure RBAC; Microsoft Entra Agent ID when it applies",
        ],
        [
            "Traces and cost",
            "Application Insights through the Azure Monitor OpenTelemetry exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`)",
        ],
        [
            "Eval gate",
            "Microsoft Foundry evaluations for the live model, with the same thresholds as `doctrine.yaml`; GitHub Actions blocks promotion",
        ],
        [
            "Guardrails and policy",
            "Azure AI Content Safety (prompt shields) in front of the model; Azure Policy for private networking and tags; Key Vault for any secret",
        ],
    ]
    return table(["Piece", "Azure service it maps to"], rows)


def s_tests(pd: Path, c: dict) -> str:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--co", "-q", str(pd.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    files: dict[str, int] = {}
    for line in r.stdout.splitlines():  # with -q twice (addopts has one) pytest prints "path: N"
        path, sep, n = line.rpartition(": ")
        if sep and path.endswith(".py") and n.strip().isdigit():
            f = path.rsplit("/", 1)[-1]
            files[f] = files.get(f, 0) + int(n)
    rows = [[f"`{f}`", n] for f, n in sorted(files.items())]
    rows.append(["**total**", f"**{sum(files.values())}**"])
    return table(["Test file", "Tests"], rows)


def s_status(pd: Path, c: dict) -> str:
    return f"Maturity (self-rated in `doctrine.yaml`): **Level {c['maturity']['level']}**, {c['maturity']['rationale']}. Next rung: {c['maturity']['next_rung']}."


SECTIONS = {k[2:]: v for k, v in globals().items() if k.startswith("s_")}


def main(argv: list[str]) -> int:
    pd = project_dir(argv[0])
    c = card(pd)
    names = list(SECTIONS) if argv[1] == "all" else argv[1:]
    print("\n\n".join(SECTIONS[n](pd, c) for n in names))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
