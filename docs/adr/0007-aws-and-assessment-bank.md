# ADR 0007: Add an AWS Bedrock runtime and a learner assessment bank

- **Status:** Accepted

## Context

The portfolio already maps every agent onto Azure (Foundry, Container Apps, Terraform and Bicep) and runs offline against a mock model. Two course gaps were still open: there was no AWS AI service, only Azure, and there was no learner assessment for the eight course modules.

There is no standalone IT-desk project. Project 01 is the agent that answers IT policy questions, so that graph is the one that moves.

## Decision

Keep project 01 where it is. Add `aws-it-desk-agent/` which runs the same graph over an IT playbook, calls Amazon Bedrock (Claude or Llama) only when `IT_DESK_PROVIDER=bedrock`, and ships Terraform for Bedrock AgentCore Runtime or ECS Fargate with CloudWatch logs. The cost write-up multiplies tokens measured on the offline graph by published list prices. It is not a live bill.

Add `assessment-bank/` with one YAML bank per module, pytest labs, a FastAPI app, mock auth and an in-memory store by default. The Azure IaC (Terraform and Bicep) targets Container Apps and Cosmos DB with keys disabled. The Entra External ID app registration is Terraform-only, because it is a Microsoft Graph object and Bicep at resource-group scope does not own it. Bicep takes the tenant, subdomain and client id as parameters.

CI plans both stacks with mocked providers. Neither stack is applied.

## Consequences

- Reviewers can run both additions with no cloud account. The live paths stay unexercised until an AWS account and an External ID tenant exist, and the READMEs say so.
- The AWS stack has no Bicep twin. ADR 0001's "change both tools" rule does not apply to a non-Azure stack; the Terraform README records that.
- Lab grading runs learner code in a short-lived subprocess. That is enough for these exercises and is not a sandbox.
- The checked-in cost table will go stale if a vendor changes a list price. `scripts/render_docs.py` regenerates it from `pricing.py`, which is the file to edit.
