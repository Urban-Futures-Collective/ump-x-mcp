"""Negative-path token tests per mcp-integration-strategy.md §11:
expired token, wrong issuer, wrong audience, manipulated signature."""

import pytest

from tests.conftest import AUDIENCE, ISSUER, make_token
from ump_mcp.adapters.keycloak_jwt import KeycloakJwtValidationAdapter
from ump_mcp.ports import IdentityValidationError

JWKS_URL = "https://auth.example.com/realms/UMP/protocol/openid-connect/certs"


@pytest.fixture
def adapter(jwks_server):
    return KeycloakJwtValidationAdapter(
        jwks_url=JWKS_URL, issuer=ISSUER, audience=AUDIENCE
    )


def test_valid_token(adapter, rsa_keypair):
    token = make_token(rsa_keypair)
    user = adapter.validate(token)
    assert user.subject == "user-123"
    assert user.raw_token == token
    assert not user.is_anonymous


def test_expired_token_rejected(adapter, rsa_keypair):
    token = make_token(rsa_keypair, expires_in=-60)
    with pytest.raises(IdentityValidationError, match="expired|Invalid"):
        adapter.validate(token)


def test_wrong_issuer_rejected(adapter, rsa_keypair):
    token = make_token(rsa_keypair, issuer="https://evil.example.com/realms/UMP")
    with pytest.raises(IdentityValidationError):
        adapter.validate(token)


def test_wrong_audience_rejected(adapter, rsa_keypair):
    token = make_token(rsa_keypair, audience="somebody-else")
    with pytest.raises(IdentityValidationError):
        adapter.validate(token)


def test_manipulated_signature_rejected(adapter, other_rsa_keypair):
    # Signed with a key that is not in the realm's JWKS (kid matches, key doesn't).
    token = make_token(other_rsa_keypair)
    with pytest.raises(IdentityValidationError):
        adapter.validate(token)


def test_garbage_token_rejected(adapter):
    with pytest.raises(IdentityValidationError):
        adapter.validate("not.a.jwt")


def test_audience_check_optional(jwks_server, rsa_keypair):
    adapter = KeycloakJwtValidationAdapter(
        jwks_url=JWKS_URL, issuer=ISSUER, audience=None
    )
    token = make_token(rsa_keypair, audience="whatever")
    assert adapter.validate(token).subject == "user-123"
