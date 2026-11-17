# `aws-it-desk-agent/tests`

Offline tests. No AWS account and no Bedrock call.

| File | What it does |
|---|---|
| [`test_agent.py`](test_agent.py) | Cited playbook answers, a stripped injection, and an honest miss. |
| [`test_bedrock.py`](test_bedrock.py) | Claude and Llama request bodies, the mock default, and a timeout that degrades. |
| [`test_compare.py`](test_compare.py) | Stable cost table, and the Terraform resources the write-up depends on. |
| [`test_service.py`](test_service.py) | `/ping`, `/invocations`, `/ask`, and the CloudWatch sink payload. |
