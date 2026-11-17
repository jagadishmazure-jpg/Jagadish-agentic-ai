"""Sign-in. Mock bearer tokens locally; Entra External ID (CIAM) RS256 tokens when configured."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

_MOCK_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class Principal(BaseModel):
    learner_id: str
    name: str


class AuthError(Exception):
    pass


@dataclass
class AuthSettings:
    mode: str
    audience: str = ""
    issuer: str = ""
    jwks_url: str = ""
    jwks_client: Any = None


def settings_from_env(env: dict[str, str] | None = None) -> AuthSettings:
    env = dict(os.environ) if env is None else env
    mode = env.get("ASSESSMENT_AUTH_MODE", "mock").strip().lower() or "mock"
    if mode == "mock":
        return AuthSettings(mode="mock")
    if mode != "entra":
        raise RuntimeError("ASSESSMENT_AUTH_MODE must be mock or entra")
    tenant = env.get("ENTRA_TENANT_ID", "").strip()
    audience = env.get("ENTRA_CLIENT_ID", "").strip()
    issuer = env.get("ENTRA_AUTHORITY", "").strip()
    subdomain = env.get("ENTRA_TENANT_SUBDOMAIN", "").strip()
    if not issuer and tenant and subdomain:
        issuer = f"https://{subdomain}.ciamlogin.com/{tenant}/v2.0"
    if not (tenant and audience and issuer):
        raise RuntimeError(
            "entra mode needs ENTRA_TENANT_ID, ENTRA_CLIENT_ID and "
            "ENTRA_AUTHORITY or ENTRA_TENANT_SUBDOMAIN"
        )
    jwks = env.get("ENTRA_JWKS_URL", "").strip()
    if not jwks and subdomain and tenant:
        jwks = f"https://{subdomain}.ciamlogin.com/{tenant}/discovery/v2.0/keys"
    return AuthSettings(mode="entra", audience=audience, issuer=issuer, jwks_url=jwks)


def principal_from_token(token: str, settings: AuthSettings) -> Principal:
    if settings.mode == "mock":
        learner = token.removeprefix("mock:")
        if not _MOCK_ID.fullmatch(learner):
            raise AuthError("invalid mock token")
        return Principal(learner_id=learner, name=learner)
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - pyjwt is a dependency of mcp
        raise AuthError("PyJWT is not installed") from exc
    client = settings.jwks_client
    if client is None:
        from jwt import PyJWKClient

        client = PyJWKClient(settings.jwks_url)
    try:
        signing = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing.key,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except Exception as exc:
        raise AuthError("invalid token") from exc
    learner = claims.get("oid") or claims.get("sub")
    if not learner:
        raise AuthError("token has no subject")
    return Principal(learner_id=str(learner), name=str(claims.get("name") or learner))
