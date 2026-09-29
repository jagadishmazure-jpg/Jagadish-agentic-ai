# `modules/containerapp`

One Container App (HTTP service or KEDA queue worker) on a user-assigned identity, pulling from ACR with that identity. The image is ignored after creation because the pipeline rolls images.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
