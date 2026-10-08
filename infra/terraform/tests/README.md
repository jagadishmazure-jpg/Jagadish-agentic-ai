# `infra/terraform/tests`

`terraform test` plans against mocked providers (no credentials, nothing created) and checks CAF names, tags, and the dev / prod profile.

| File | What it does |
|---|---|
| [`plan.tftest.hcl`](plan.tftest.hcl) | Offline `terraform test`: plans with mocked providers and asserts naming, tags, the per-profile shape, private networking (2 private endpoints, the NSG), the default alert rules and diagnostic settings and Defender off by default. No Azure credentials needed. |
