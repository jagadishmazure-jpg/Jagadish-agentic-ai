# `assessment_bank`

FastAPI app for the course assessment bank.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package marker. |
| [`app.py`](app.py) | Routes: health, modules, quiz, lab, progress. Auth on every route except health. |
| [`auth.py`](auth.py) | Mock bearer tokens, or RS256 validation against an Entra External ID issuer. |
| [`bank.py`](bank.py) | YAML loader and the public view that drops answer keys. |
| [`grading.py`](grading.py) | Quiz scoring and the pytest subprocess for labs. |
| [`store.py`](store.py) | In-memory progress, and a Cosmos DB data-plane client using an Entra token. |
