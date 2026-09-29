# `shared/api`: portfolio HTTP API

A small FastAPI app that makes the portfolio runnable as a service. It is what the container image and the Azure deployment run. Every call uses the deterministic mock model unless `PORTFOLIO_ALLOW_LIVE=1`.

```bash
uvicorn shared.api.app:create_app --factory --port 8000
curl localhost:8000/healthz
curl -X POST localhost:8000/projects/03-refund-agent/evals
```

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package marker. |
| [`app.py`](app.py) | `create_app()`: `/healthz`, `/readyz`, `/projects`, `/projects/{id}` (doctrine summary + checked-in scores), `POST /projects/{id}/evals` (rerun the golden set, no writes). |
