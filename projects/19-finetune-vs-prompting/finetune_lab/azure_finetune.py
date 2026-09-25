"""OPTIONAL: run the same JSONL through Azure OpenAI supervised fine-tuning.

Dry-run by default. It validates the files and prints the exact requests it *would* send.
Nothing touches Azure unless you pass ``--execute`` and set the environment variables
below. Tests and CI only ever exercise the dry run, and ``--execute`` refuses to start
when ``CI`` or ``PYTEST_CURRENT_TEST`` is set.

    python projects/19-finetune-vs-prompting/run.py azure                      # dry run
    python projects/19-finetune-vs-prompting/run.py azure --execute            # upload + train
    python projects/19-finetune-vs-prompting/run.py azure --execute --deploy   # + deploy

Environment for ``--execute``:
    AZURE_OPENAI_ENDPOINT   https://<resource>.openai.azure.com
    AZURE_OPENAI_API_KEY    data-plane key (or swap in Entra ID auth)
and additionally for ``--deploy`` (control plane, separate auth):
    AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_OPENAI_RESOURCE,
    AZURE_MANAGEMENT_TOKEN  (e.g. from ``az account get-access-token``)

API shapes follow Microsoft Learn, "Customize a model with fine-tuning" (checked
2026-09-25): https://learn.microsoft.com/azure/ai-foundry/openai/how-to/fine-tuning

* data plane via the v1 endpoint: ``OpenAI(base_url=<endpoint>/openai/v1/)``;
  ``files.create(purpose="fine-tune")``; ``fine_tuning.jobs.create(model, training_file,
  validation_file, suffix, seed, method={"type": "supervised", ...},
  extra_body={"trainingType": ...})``; ``jobs.retrieve`` / ``jobs.list_events`` to poll;
* files must be UTF-8 **with a BOM**, under 512 MB, with at least 10 training examples;
  the suffix is at most 18 characters and may not contain a period;
* deployment is a control-plane ``PUT .../Microsoft.CognitiveServices/accounts/<resource>/
  deployments/<name>?api-version=2024-10-01`` with ``properties.model = {format: OpenAI,
  name: <fine_tuned_model>, version: "1"}``.

Pricing is not estimated here: training is billed per token and a deployed fine-tuned model
also bills hourly hosting while deployed. See the official pricing page:
https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from finetune_lab.dataset import validate_chat_file
from shared.observability import estimate_tokens

DOCS_URL = "https://learn.microsoft.com/azure/ai-foundry/openai/how-to/fine-tuning"
PRICING_URL = "https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/"
# Supervised fine-tuning (SFT) base models listed in the Learn table above, as of 2026-09-25.
# (o4-mini and gpt-5 are RFT-only; the open models are Foundry-resource only.)
SFT_MODELS = (
    "gpt-4o-mini-2024-07-18",
    "gpt-4o-2024-08-06",
    "gpt-4.1-2025-04-14",
    "gpt-4.1-mini-2025-04-14",
    "gpt-4.1-nano-2025-04-14",
)
TRAINING_TYPES = ("Standard", "GlobalStandard", "Developer")
MAX_FILE_BYTES = 512 * 1024 * 1024
MIN_TRAIN = 10
DATA_ENV = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")
DEPLOY_ENV = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "AZURE_OPENAI_RESOURCE",
    "AZURE_MANAGEMENT_TOKEN",
)
MGMT_API_VERSION = "2024-10-01"
TERMINAL = {"succeeded", "failed", "cancelled"}
DATA = Path(__file__).resolve().parents[1] / "data"


class PlanError(ValueError):
    pass


def with_bom(src: Path, dst_dir: Path) -> Path:
    """Copy a JSONL file re-encoded as UTF-8 with a BOM (required by the service)."""
    dst = dst_dir / src.name
    dst.write_text(src.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    return dst


def plan(args: argparse.Namespace) -> dict[str, Any]:
    """Validate inputs and describe every request. Pure: no network, no env access."""
    problems = []
    if args.model not in SFT_MODELS:
        problems.append(f"{args.model} is not an SFT base model (supported: {SFT_MODELS})")
    if len(args.suffix) > 18 or "." in args.suffix:
        problems.append("suffix must be <= 18 characters with no '.'")
    files = {}
    for role, path in (("training", args.train), ("validation", args.val)):
        if not path.exists():
            problems.append(f"{role} file missing: {path}")
            continue
        errs = validate_chat_file(path)
        rows = path.read_text(encoding="utf-8-sig").splitlines()
        if errs:
            problems.append(f"{role}: {errs[:3]}")
        if path.stat().st_size >= MAX_FILE_BYTES:
            problems.append(f"{role} file >= 512 MB")
        files[role] = {
            "path": str(path),
            "examples": len(rows),
            "approx_tokens": sum(estimate_tokens(r) for r in rows),
        }
    if files.get("training", {}).get("examples", 0) < MIN_TRAIN:
        problems.append(f"need >= {MIN_TRAIN} training examples")
    if problems:
        raise PlanError("; ".join(problems))
    job: dict[str, Any] = {
        "model": args.model,
        "training_file": "<file id from upload>",
        "validation_file": "<file id from upload>",
        "suffix": args.suffix,
        "seed": args.seed,
        "extra_body": {"trainingType": args.training_type},
    }
    if args.epochs:
        job["method"] = {
            "type": "supervised",
            "supervised": {"hyperparameters": {"n_epochs": args.epochs}},
        }
    steps: list[dict[str, Any]] = [
        {"call": "files.create", "purpose": "fine-tune", "file": f"{r} (UTF-8 BOM copy)"}
        for r in files
    ]
    steps += [
        {"call": "fine_tuning.jobs.create", **job},
        {"call": "fine_tuning.jobs.retrieve", "until": sorted(TERMINAL)},
    ]
    if args.deploy:
        steps.append(
            {
                "call": "PUT management.azure.com/.../accounts/<resource>/deployments/"
                f"{args.deployment_name}?api-version={MGMT_API_VERSION}",
                "body": deploy_body("<fine_tuned_model>", args.deploy_sku),
            }
        )
    return {
        "files": files,
        "job": job,
        "steps": steps,
        "billing_note": f"training is billed per token and a deployed model bills hourly "
        f"hosting; no estimate is made here, see {PRICING_URL}",
        "docs": DOCS_URL,
    }


def deploy_body(model_name: str, sku: str) -> dict[str, Any]:
    return {
        "sku": {"name": sku, "capacity": 1},
        "properties": {"model": {"format": "OpenAI", "name": model_name, "version": "1"}},
    }


def require_env(names: tuple[str, ...]) -> dict[str, str]:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise SystemExit(f"--execute needs environment variables: {', '.join(missing)}")
    return {n: os.environ[n] for n in names}


def execute(args: argparse.Namespace, the_plan: dict[str, Any]) -> dict[str, Any]:
    if os.getenv("CI") or os.getenv("PYTEST_CURRENT_TEST"):
        raise SystemExit("refusing to call Azure from CI or tests")
    env = require_env(DATA_ENV + (DEPLOY_ENV if args.deploy else ()))
    from openai import OpenAI  # optional extra: uv sync --extra openai

    client = OpenAI(
        api_key=env["AZURE_OPENAI_API_KEY"],
        base_url=f"{env['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/v1/",
    )
    with tempfile.TemporaryDirectory() as tmp:
        ids = {}
        for role, path in (("training", args.train), ("validation", args.val)):
            with with_bom(path, Path(tmp)).open("rb") as fh:
                ids[role] = client.files.create(file=fh, purpose="fine-tune").id
            client.files.wait_for_processing(ids[role])
            print(f"uploaded {role}: {ids[role]}")
    job_args = {**the_plan["job"], "training_file": ids["training"]}
    job_args["validation_file"] = ids["validation"]
    job = client.fine_tuning.jobs.create(**job_args)
    print(f"job {job.id}: {job.status}")
    deadline = time.monotonic() + args.timeout_minutes * 60
    while job.status not in TERMINAL:
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for {job.id} (still {job.status})")
        time.sleep(args.poll_seconds)
        job = client.fine_tuning.jobs.retrieve(job.id)
        events = client.fine_tuning.jobs.list_events(fine_tuning_job_id=job.id, limit=3)
        latest = events.data[0].message if events.data else ""
        print(f"  {job.status}  {latest}")
    out: dict[str, Any] = {"job_id": job.id, "status": job.status}
    if job.status != "succeeded":
        return out
    out["fine_tuned_model"] = job.fine_tuned_model
    if args.deploy:
        out["deployment"] = deploy(env, args.deployment_name, job.fine_tuned_model, args)
    return out


def deploy(env: dict[str, str], name: str, model: str, args: argparse.Namespace) -> Any:
    import urllib.request

    url = (
        "https://management.azure.com/subscriptions/"
        f"{env['AZURE_SUBSCRIPTION_ID']}/resourceGroups/{env['AZURE_RESOURCE_GROUP']}"
        f"/providers/Microsoft.CognitiveServices/accounts/{env['AZURE_OPENAI_RESOURCE']}"
        f"/deployments/{name}?api-version={MGMT_API_VERSION}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(deploy_body(model, args.deploy_sku)).encode(),
        method="PUT",
        headers={
            "Authorization": f"Bearer {env['AZURE_MANAGEMENT_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Azure OpenAI fine-tuning (dry run unless --execute).")
    ap.add_argument("--train", type=Path, default=DATA / "train.jsonl")
    ap.add_argument("--val", type=Path, default=DATA / "val.jsonl")
    ap.add_argument("--model", default="gpt-4.1-mini-2025-04-14", help="SFT base model")
    ap.add_argument("--suffix", default="loan-doc-cls")
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--epochs", type=int, default=0, help="0 = service default")
    ap.add_argument("--training-type", choices=TRAINING_TYPES, default="GlobalStandard")
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--deployment-name", default="loan-doc-cls-ft")
    ap.add_argument("--deploy-sku", default="standard")
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--timeout-minutes", type=int, default=240)
    ap.add_argument("--execute", action="store_true", help="actually call Azure")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        the_plan = plan(args)
    except PlanError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(the_plan, indent=2))
    if not args.execute:
        print("\nDRY RUN: nothing was sent. Re-run with --execute (and env vars) to train.")
        return 0
    print(json.dumps(execute(args, the_plan), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
