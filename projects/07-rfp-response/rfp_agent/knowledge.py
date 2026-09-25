"""Approved answer library (knowledge base) + the sample RFP."""

from __future__ import annotations

import re

KB: dict[str, dict[str, str]] = {
    "KB-SEC-001": {
        "title": "Encryption at rest",
        "text": "Customer data is encrypted at rest with AES-256 using keys managed "
        "in Azure Key Vault, rotated every 90 days.",
    },
    "KB-SEC-002": {
        "title": "Encryption in transit",
        "text": "All traffic is encrypted in transit with TLS 1.2 or higher; HSTS is "
        "enforced on all endpoints.",
    },
    "KB-SEC-003": {
        "title": "SSO and provisioning",
        "text": "We support SSO via SAML 2.0 and OIDC with Entra ID, Okta and Ping, "
        "and user provisioning via SCIM 2.0.",
    },
    "KB-SEC-004": {
        "title": "Security track record (legacy wording)",
        "text": "We maintain a 24x7 security operations center. We have never been "
        "breached and guarantee 100% security.",
    },
    "KB-CMP-001": {
        "title": "Certifications",
        "text": "We hold SOC 2 Type II and ISO 27001 certifications, renewed "
        "annually; reports are available under NDA.",
    },
    "KB-CMP-002": {
        "title": "GDPR",
        "text": "We are GDPR compliant, offer a DPA with SCCs, and host EU customer "
        "data in EU regions.",
    },
    "KB-OPS-001": {
        "title": "Availability SLA",
        "text": "Our SLA guarantees 99.9% monthly uptime with service credits.",
    },
    "KB-OPS-002": {
        "title": "Backup and DR",
        "text": "Backups run every 4 hours; disaster recovery targets are RPO 4 "
        "hours and RTO 8 hours, tested twice a year.",
    },
    "KB-EXP-001": {
        "title": "Export classification",
        "text": "Our encryption module is classified 5D992 under the EAR; ITAR "
        "controlled data is not supported.",
    },
}

RFP = """# RFP-2026-117: Contoso Health - Analytics Platform

## Security
Q1. How is customer data encrypted at rest and in transit?
Q2. Do you support SSO and automated user provisioning (SCIM)?
Q3. Describe your security track record.

## Compliance
Q4. Which certifications do you hold (SOC 2, ISO 27001)?
Q5. How do you comply with GDPR and where is EU customer data hosted?

## Operations
Q6. What uptime SLA do you offer?
Q7. What are your backup frequency, RPO and RTO?
Q8. Do you offer an on-premises air-gapped deployment?

## Legal
Q9. Can the platform process ITAR controlled data, and what is the export classification?
"""


def parse_rfp(text: str) -> list[dict]:
    """Deterministic planner fallback: '## Section' headers and 'Qn.' lines."""
    sections: list[dict] = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        name, *lines = block.strip().splitlines()
        qs = [
            {"id": m.group(1), "text": m.group(2).strip()}
            for ln in lines
            if (m := re.match(r"(Q\d+)\.\s*(.+)", ln.strip()))
        ]
        sections.append({"name": name.strip(), "questions": qs})
    return sections
