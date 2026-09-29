# `.github/scripts`

Shell steps called by the deploy and teardown workflows.

| File | What it does |
|---|---|
| [`deploy.sh`](deploy.sh) | `provision` (Terraform apply or Bicep `az deployment group create`), `push` / `import` the API image, `roll` the Container App, `smoke` test `/healthz` and `/projects`, `destroy`. |
