"""Entra External ID token checks, and the Cosmos request shape, with no cloud calls."""

from datetime import UTC, datetime

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from assessment_bank.auth import AuthSettings, principal_from_token
from assessment_bank.store import Attempt, CosmosStore

ISSUER = "https://assessmentbank.ciamlogin.com/tenant/v2.0"
AUDIENCE = "api-client-id"


class StaticKey:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token: str):
        return self


def _settings(key) -> AuthSettings:
    return AuthSettings(
        mode="entra",
        audience=AUDIENCE,
        issuer=ISSUER,
        jwks_url="https://example.test/keys",
        jwks_client=StaticKey(key),
    )


def test_entra_token_accepts_oid_and_rejects_the_wrong_audience():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"oid": "learner-1", "name": "Ada", "aud": AUDIENCE, "iss": ISSUER},
        key,
        algorithm="RS256",
    )
    principal = principal_from_token(token, _settings(key.public_key()))
    assert principal.learner_id == "learner-1"
    assert principal.name == "Ada"
    other = jwt.encode(
        {"oid": "learner-1", "aud": "someone-else", "iss": ISSUER},
        key,
        algorithm="RS256",
    )
    try:
        principal_from_token(other, _settings(key.public_key()))
    except Exception as exc:
        assert "invalid token" in str(exc)
    else:
        raise AssertionError("wrong audience was accepted")


def test_cosmos_save_and_query_use_aad_and_the_partition_key():
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, headers, body))
        if headers.get("x-ms-documentdb-isquery") == "True":
            return 200, {"Documents": [body_doc]}
        return 201, body

    store = CosmosStore(
        "https://cosmosassess.documents.azure.com",
        "assessments",
        "progress",
        token_provider=lambda: "token-1",
        transport=transport,
    )
    attempt = Attempt(
        id="a1",
        learner_id="learner-1",
        module_id="foundations",
        kind="quiz",
        item_id="foundations",
        score=1,
        points=4,
        max_points=4,
        passed=True,
        submitted_at=datetime.now(UTC).isoformat(),
    )
    body_doc = attempt.model_dump()
    body_doc["learnerId"] = "learner-1"
    store.save(attempt)
    listed = store.list_for("learner-1")
    assert listed[0].id == "a1"
    save_headers = calls[0][2]
    assert save_headers["Authorization"] == "type=aad&ver=1.0&sig=token-1"
    assert save_headers["x-ms-documentdb-partitionkey"] == '["learner-1"]'
    assert calls[0][1].endswith("/dbs/assessments/colls/progress/docs")
    assert calls[1][3]["query"].startswith("SELECT * FROM c")
    assert "AccountKey" not in save_headers["Authorization"]
