# Architecture decision records

Short records of the decisions that shape this repo: the context at the time, what was chosen, and what it costs. A new decision gets the next number; a reversed decision is marked `Superseded` and links to its replacement rather than being deleted.

| File | What it does |
|---|---|
| [`README.md`](README.md) | This index |
| [`0001-bicep-and-terraform.md`](0001-bicep-and-terraform.md) | Keep Bicep and add a Terraform twin |
| [`0002-offline-mocks-by-default.md`](0002-offline-mocks-by-default.md) | Run offline against deterministic mocks by default |
| [`0003-oidc-and-managed-identity.md`](0003-oidc-and-managed-identity.md) | Use OIDC federation for CI and managed identities at runtime |
| [`0004-eval-gates-block-release.md`](0004-eval-gates-block-release.md) | Eval gates block the build |
| [`0005-deploy-gated-off.md`](0005-deploy-gated-off.md) | Ship the deploy pipeline switched off |
| [`0006-doctrine-cards-as-promotion-gate.md`](0006-doctrine-cards-as-promotion-gate.md) | Doctrine cards are a promotion gate |
