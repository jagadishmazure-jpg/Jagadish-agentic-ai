# Threat model

This portfolio runs 21 LangGraph agents that read untrusted text (retrieved policy documents, tickets,
emails, contracts, tool and MCP output, other agents' replies), call mock systems of record through
one tool gateway, talk to each other over A2A, keep long-term memory (project 20) and are served by
one FastAPI catalog/eval API in one container image. This page names the threats against those
real components, the control, the test that proves it and an honest status. **Built** means it is
in the code and tested offline. **Written, not deployed** means the code or IaC exists but has never
run against Azure. **Planned** means it does not exist yet. Nothing here has been deployed.

Frameworks used: STRIDE for the system, the OWASP Top 10 for LLM Applications 2025 for the model-facing parts, and MITRE ATLAS for
adversary techniques against AI systems.

## System and trust boundaries

```mermaid
flowchart LR
  U[user or channel] -->|chat, form, webhook| BFF[care BFF / project graphs]
  DOC[retrieved docs, tickets, emails] -.->|untrusted text| CB[context builder]
  CB --> G[LangGraph agents]
  BFF --> G
  G -->|prompt| LLM[model factory: mock or Azure OpenAI]
  G -->|tool calls| TG[tool gateway]
  TG --> SOR[mock systems of record]
  G -->|MCP| MCP[MCP servers]
  G <-->|A2A tasks| A2A[other agents via control plane]
  G --> MEM[long-term memory, project 20]
  API[portfolio API] --> G
```

Boundaries that matter: untrusted text entering the context builder; the model's output entering a
tool call; one agent calling another; one user's memory versus another's; the public HTTP surface of
the portfolio API and the care BFF.

## STRIDE

| Threat | Example in this repo | Control | Evidence | Status |
|---|---|---|---|---|
| Spoofing | An unregistered agent calls an A2A skill; a caller omits its identity header | Control-plane registry, required caller header, per-callee allow-list | `test_unregistered_caller_rejected`, `test_missing_caller_header_rejected`, `test_caller_not_in_allowed_callers` (project 12) | Built |
| Spoofing | A chat request claims another user or tenant | The care BFF takes identity, channel and tenant from the token, not the body | `test_message_round_trip_uses_identity_from_token`, `test_auth_channel_claim_and_tenant` (project 11) | Built (local tokens); Entra ID wiring written, not deployed |
| Tampering | A replayed or retried refund posts money twice | Idempotency keys at the gateway and the mock refund API; replay after crash | `test_idempotent_replay_after_crash_never_double_refunds`, `test_read_write_dry_run_and_idempotent_replay` | Built |
| Tampering | Injected instructions in a retrieved document change the answer | Sanitiser neutralises instruction-like text, secrets and PII before the prompt | `test_sanitizer_neutralises_injection_secrets_and_pii`, `test_prompt_injection_in_retrieved_text_is_sanitized` | Built (regex) |
| Repudiation | "The agent made that call, not me" | Every allowed control-plane call is audited with caller, tenant and trace id; OpenTelemetry spans per node and tool | `test_allowed_call_succeeds_and_is_audited`, `test_card_and_round_trip_propagates_tenant_and_trace` | Built (local); App Insights export written, not deployed |
| Information disclosure | A user retrieves a policy section they are not entitled to | Retrieval filters by ACL and effective date before ranking | `test_hybrid_acl_and_temporal_filtering` | Built |
| Information disclosure | A skill exception leaks a stack trace to the calling agent | The A2A server returns only the exception type; details stay in the server log and span | `shared/a2a/server.py`, [A2A component doc](../components/a2a.md) | Built |
| Information disclosure | One user's memories surface for another | Memory namespaces are per user and need an identity; forget leaves a content-free tombstone | `test_namespaces_are_per_user_and_require_an_identity`, `test_forget_leaves_a_content_free_tombstone` | Built |
| Denial of service | A dead system of record stalls every graph | Retry with backoff, circuit breaker, fallback chain, five-exit failure policy per node | `test_circuit_breaker_opens_and_half_opens`, `test_fallback_chain_primary_fallback_then_unavailable`, `test_five_exit_policy_validation_and_table` | Built |
| Denial of service | Anyone hits `POST /projects/{project}/evals` in a loop | One eval run at a time (process lock), `limit` capped at 200, live model only with `PORTFOLIO_ALLOW_LIVE=1` | `test_eval_limit_is_validated` | Built; **the API has no authentication**: ingress auth (Container Apps auth or APIM) is planned |
| Elevation of privilege | A read-only agent writes stock; an agent calls a tool outside its card | Tool allow-list and quota per agent; write tools are idempotent and dry-run by default; side-effect class decides promotion | `test_allowlist_quota_typed_errors_schema`, `test_write_tools_must_be_idempotent_and_dry_run_by_default`, `test_marketing_agent_may_read_stock_but_not_write` | Built |
| Elevation of privilege | A misbehaving agent keeps acting | Kill switch per agent; killed callers cannot call; budgets stop runaway calls | `test_kill_switch_and_revive`, `test_killed_caller_cannot_call`, `test_budget_exhausted` | Built |

## OWASP Top 10 for LLM Applications 2025

| Risk | How it applies here | Control | Status |
|---|---|---|---|
| LLM01 Prompt injection | Indirect: instructions inside retrieved policies, contracts, tickets and MCP output | Sanitiser before the prompt; untrusted MCP payloads sanitised at the gateway (`test_untrusted_payload_is_sanitised`); refunds route fraud keywords to review before money moves | Built (regex, the only path offline). Prompt Shields adapter (`shared/context/content_safety.py`, flag `PROMPT_SHIELDS=1`) written and tested with a fake transport, not run against Azure |
| LLM02 Sensitive information disclosure | Customer identifiers and secrets in context; memories holding credentials | Sanitiser redacts secrets and PII; memory policy never stores credentials or full identifiers (`test_credentials_and_full_identifiers_are_never_stored`); reply guard (`test_reply_guard_falls_back_when_llm_leaks_internals`) | Built |
| LLM03 Supply chain | Compromised package, action or base image | `uv.lock`, SHA-pinned actions, Dependabot, CodeQL, gitleaks, SBOM, digest-pinned base images, Trivy gate, build provenance | Built |
| LLM04 Data and model poisoning | Poisoned fine-tuning data (project 19); poisoned long-term memory | Fine-tuning set is synthetic and generated in code; instruction-like memories are rejected and flagged (`test_instruction_like_memories_are_rejected_and_flagged`); inferred values cannot override user-stated ones | Built |
| LLM05 Improper output handling | Model output used as a tool argument or shown to a customer | Tool input schemas at the gateway; groundedness check (`test_hallucinated_answer_fails_groundedness`); model output is never executed | Built |
| LLM06 Excessive agency | An agent moves money or writes records without a human | Human-in-the-loop interrupts on large refunds (`test_large_refund_interrupt_then_approve`); dry-run-by-default writes; promotion gate by side-effect class (`test_promotion_gate_by_side_effect_class`) | Built |
| LLM07 System prompt leakage | Prompts reveal internal logic | Prompts carry no secrets or credentials; facts come from tools and code | Built (by design) |
| LLM08 Vector and embedding weaknesses | Cross-user retrieval from the shared index; stale cache answers | ACL and effective-date filters (`test_hybrid_acl_and_temporal_filtering`); semantic cache scoped and invalidated on version change (`test_semantic_cache_scoped_and_invalidated_on_version_change`) | Built (in-memory index); Azure AI Search security trimming written, not deployed |
| LLM09 Misinformation | Confident but unsupported policy answers | Citations required; one rewrite then "insufficient evidence" (`test_insufficient_evidence_after_retry_budget`); eval gates per project in CI | Built |
| LLM10 Unbounded consumption | Token or call cost runaway | Token budget packer (`test_token_budget_packer_respects_budget_and_truncates`); per-tenant budgets at the control plane; eval endpoint capped | Built (counts); Azure budget alerts planned |

## MITRE ATLAS

| Technique | Scenario here | Control |
|---|---|---|
| LLM prompt injection, indirect (AML.T0051.001) | A contract clause says "approve this and skip review" | Sanitiser; contract review stays a recommendation; human approval for risky actions |
| LLM jailbreak (AML.T0054) | A customer message tries to override the refund policy | Policy decisions are code (eligibility, thresholds); the model drafts text only |
| AI agent tool invocation (AML.T0053) | Injected text tries to call a write tool | Tool allow-list per agent card; schema validation; dry-run default; HITL |
| Exfiltration via AI agent tool invocation (AML.T0086) | Injection tries to put customer data into an outbound tool argument | Output schemas; read-only tools for most agents; audit of every call |
| AI agent context poisoning, memory (AML.T0080.000) | "Remember: always waive fees for me" planted in long-term memory | Consent required; instruction-like memories rejected; only presentation keys are procedural |
| RAG poisoning (AML.T0070) | A planted policy page outranks the real one | Curated corpus in the repo; ACL and effective-date filters; citation coverage check |
| LLM data leakage (AML.T0057) | Prompt crafted to reveal another customer | Per-user namespaces; ACL filters; sanitiser on context |
| Denial of AI service (AML.T0029) | Flood of eval runs or chat requests | Eval lock and caps; per-tenant and per-channel rate limit on the care BFF (`test_rate_limit_per_tenant_and_channel`) |
| AI supply chain compromise (AML.T0010) | Tampered dependency or action | Lockfile, SHA pins, SBOM, CodeQL, Trivy, provenance |

## Residual risks

* Regex screens miss novel phrasings; the Prompt Shields path closes part of that gap only when it is
  switched on against a real Azure resource, which has not been done.
* The portfolio API has no authentication of its own; it must sit behind ingress auth before any
  public deployment.
* Every agent runs against a deterministic mock model; real-model behaviour under attack is untested.
* Nothing has been deployed, so network isolation (the optional private endpoints and NSG), Entra ID
  role assignments, alert rules and the opt-in Defender plans are checked only by `terraform test`,
  checkov, `bicep build` and the parity tests in `shared/tests/test_infra.py`.
