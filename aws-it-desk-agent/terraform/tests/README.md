# `terraform/tests`

Offline plans for the IT desk stack. The AWS provider is mocked, so no account is contacted.

| File | What it does |
|---|---|
| [`plan.tftest.hcl`](plan.tftest.hcl) | AgentCore stays on the mock, Fargate starts zero tasks, live model is opt-in. |
