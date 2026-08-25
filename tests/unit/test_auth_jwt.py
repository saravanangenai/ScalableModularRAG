import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from packages.auth.config import Settings
from packages.auth.jwt import verify_token
from packages.exceptions import AuthenticationError

ISSUER = "http://localhost:8080/realms/mm-rag"
AUDIENCE = "mm-rag-api"


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._key)


def _settings() -> Settings:
    return Settings(keycloak_issuer_url=ISSUER, keycloak_audience=AUDIENCE, _env_file=None)


def _make_token(private_pem: bytes, **claim_overrides) -> str:
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    payload.update(claim_overrides)
    return pyjwt.encode(payload, private_pem, algorithm="RS256")


def test_verify_token_accepts_valid_token(keypair):
    private_pem, public_pem = keypair
    token = _make_token(private_pem)

    claims = verify_token(token, _settings(), jwk_client=_FakeJWKClient(public_pem))

    assert claims["sub"] == "user-123"


def test_verify_token_rejects_expired_token(keypair):
    private_pem, public_pem = keypair
    token = _make_token(private_pem, exp=int(time.time()) - 10)

    with pytest.raises(AuthenticationError):
        verify_token(token, _settings(), jwk_client=_FakeJWKClient(public_pem))


def test_verify_token_rejects_wrong_issuer(keypair):
    private_pem, public_pem = keypair
    token = _make_token(private_pem, iss="http://evil.example/realms/other")

    with pytest.raises(AuthenticationError):
        verify_token(token, _settings(), jwk_client=_FakeJWKClient(public_pem))


def test_verify_token_rejects_wrong_audience(keypair):
    private_pem, public_pem = keypair
    token = _make_token(private_pem, aud="some-other-client")

    with pytest.raises(AuthenticationError):
        verify_token(token, _settings(), jwk_client=_FakeJWKClient(public_pem))


def test_verify_token_rejects_bad_signature(keypair):
    private_pem, _ = keypair
    token = _make_token(private_pem)
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_public_pem = other_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    with pytest.raises(AuthenticationError):
        verify_token(token, _settings(), jwk_client=_FakeJWKClient(other_public_pem))
