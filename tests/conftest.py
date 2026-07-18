import json
import time
from base64 import urlsafe_b64encode

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://auth.example.com/realms/UMP"
AUDIENCE = "ump-client"
KID = "test-key"


@pytest.fixture(scope="session")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key


@pytest.fixture(scope="session")
def other_rsa_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _int_to_b64(value: int) -> str:
    byte_length = (value.bit_length() + 7) // 8
    return urlsafe_b64encode(value.to_bytes(byte_length, "big")).rstrip(b"=").decode()


@pytest.fixture(scope="session")
def jwks(rsa_keypair):
    numbers = rsa_keypair.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KID,
                "n": _int_to_b64(numbers.n),
                "e": _int_to_b64(numbers.e),
            }
        ]
    }


def make_token(
    key,
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    subject: str = "user-123",
    expires_in: int = 300,
    kid: str = KID,
    extra_claims: dict | None = None,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + expires_in,
        **(extra_claims or {}),
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def jwks_server(monkeypatch, jwks):
    """Patches PyJWKClient's fetching so no network is needed."""
    from jwt import PyJWKClient

    def fake_fetch_data(self):
        return json.loads(json.dumps(jwks))

    monkeypatch.setattr(PyJWKClient, "fetch_data", fake_fetch_data)
