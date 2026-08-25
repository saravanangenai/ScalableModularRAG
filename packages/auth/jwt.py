from functools import lru_cache

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from packages.auth.config import Settings
from packages.exceptions import AuthenticationError


@lru_cache(maxsize=1)
def _default_jwk_client(issuer_url: str) -> PyJWKClient:
    return PyJWKClient(f"{issuer_url}/protocol/openid-connect/certs")


def verify_token(token: str, settings: Settings | None = None, jwk_client: PyJWKClient | None = None) -> dict:
    """Verifies a bearer JWT's signature, expiry, issuer, and audience against the
    configured Keycloak realm. Returns the decoded claims on success. Never trusts a
    tenant_id/role claim even if present — callers must re-derive scope from Postgres."""
    settings = settings or Settings()
    client = jwk_client or _default_jwk_client(settings.keycloak_issuer_url)

    try:
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_issuer_url,
        )
    except (PyJWTError, PyJWKClientError) as exc:
        raise AuthenticationError("token verification failed", original_exception=exc) from exc
