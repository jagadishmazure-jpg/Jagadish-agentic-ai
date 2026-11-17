# `it_desk`

The IT desk playbook agent. It reuses project 01's corrective RAG graph and swaps in the IT playbook plus a Bedrock chat model.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Re-exports `ask`. |
| [`agent.py`](agent.py) | `build_agent` and `ask`. BM25 over the playbook, model from `get_model`. |
| [`bedrock.py`](bedrock.py) | Claude and Llama InvokeModel bodies, a boto3 invoker, and the mock switch. |
| [`compare.py`](compare.py) | Measures offline tokens and prints the list-price comparison. |
| [`logging.py`](logging.py) | JSON log records. Memory sink by default, CloudWatch `PutLogEvents` when configured. |
| [`playbook.py`](playbook.py) | IT desk playbook chunks, including one instruction-like span the sanitiser must strip. |
| [`pricing.py`](pricing.py) | Published model and runtime rates used by the comparison. |
| [`service.py`](service.py) | FastAPI: `/healthz`, `/ping`, `/invocations`, `/ask`. |
