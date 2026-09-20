"""The browser view at /.

A person who opens the server's address in a browser is not the audience for
JSON-RPC or a 401 challenge. These tests pin what they get instead: a page in
their own language, the endpoint they actually have to paste into a client,
and — the part that must never regress — no interference with the machine
surfaces next to it.
"""

import pytest
from starlette.testclient import TestClient

from tests.conftest import ISSUER
from ump_mcp.app import create_app
from ump_mcp.config import Settings

RESOURCE = "https://mcp.example.org/mcp"


def _settings(**overrides) -> Settings:
    base = dict(
        ump_api_base_url="http://ump.test",
        keycloak_url="https://auth.example.com",
        keycloak_realm="UMP",
        keycloak_issuer=ISSUER,
        allow_anonymous=False,
        resource_url=RESOURCE,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client(jwks_server):
    with TestClient(create_app(_settings())) as c:
        yield c


def test_root_serves_the_page_without_a_token(client):
    """Unauthenticated on purpose: whoever lands here has no token yet, and the
    page's whole job is telling them how to get one."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Urban Model Platform" in response.text


def test_page_shows_the_configured_endpoint_not_the_bare_root(client):
    """`resource_url` is the address clients must use; the page they read it
    from is served at /, so the two must not be confused."""
    response = client.get("/")

    assert RESOURCE in response.text


def test_endpoint_falls_back_to_the_request_and_honours_the_proxy_scheme(jwks_server):
    """Without `resource_url` the request is all there is — and behind the
    ingress the app only ever sees http, so a page that trusted request.scheme
    would hand out an http:// endpoint for an https:// deployment."""
    with TestClient(create_app(_settings(resource_url=None))) as c:
        response = c.get(
            "/", headers={"host": "mcp.example.org", "x-forwarded-proto": "https"}
        )

    assert "https://mcp.example.org/mcp" in response.text


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("en-GB,en;q=0.9", "en"),
        ("fr-FR,fr;q=0.9", "en"),
        ("", "en"),
    ],
)
def test_language_follows_accept_language(client, header, expected):
    response = client.get("/", headers={"accept-language": header} if header else {})

    assert f'<html lang="{expected}">' in response.text
    assert response.headers["vary"] == "Accept-Language"


def test_lang_query_parameter_overrides_the_browser(client):
    """The switch in the header has to win — a German browser reading the
    English page is a choice, not a mistake to correct on every request."""
    response = client.get("/?lang=en", headers={"accept-language": "de-DE,de;q=0.9"})

    assert '<html lang="en">' in response.text
    assert "MCP endpoint" in response.text


@pytest.mark.parametrize(("lang", "phrase"), [("en", "sign up"), ("de", "registrieren")])
def test_page_says_an_account_is_needed_first(client, lang, phrase):
    """Without a Urban Model Platform account the endpoint is a dead end, so
    the requirement comes before the connection steps and links to the sign-up."""
    body = client.get(f"/?lang={lang}").text

    assert phrase in body
    assert 'href="https://ump-x.urbanfuturescollective.org/"' in body


def test_german_page_is_actually_german(client):
    response = client.get("/?lang=de")

    assert '<html lang="de">' in response.text
    assert "MCP-Endpunkt" in response.text
    assert "MCP endpoint" not in response.text


def test_unknown_language_falls_back_instead_of_erroring(client):
    response = client.get("/?lang=xx")

    assert response.status_code == 200
    assert '<html lang="en">' in response.text


@pytest.mark.parametrize(
    ("name", "content_type"),
    [
        ("poppins-400-latin.woff2", "font/woff2"),
        ("poppins-600-latin.woff2", "font/woff2"),
        ("Satoshi-Variable.woff2", "font/woff2"),
        ("ufc-mark.png", "image/png"),
    ],
)
def test_assets_are_served_from_the_package(client, name, content_type):
    """Self-hosted on purpose: opening the page must not call out to a CDN."""
    response = client.get(f"/static/{name}")

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert "immutable" in response.headers["cache-control"]


def test_static_route_serves_nothing_but_the_allow_list(client):
    """The filename comes from the URL, and the assets share a directory with
    the licence file — only the allow-list may answer."""
    assert client.get("/static/OFL.txt").status_code == 404


def test_page_makes_no_external_requests(client):
    """No CDN, no Google Fonts, no analytics — same rule the frontend follows:
    opening the page must not connect the visitor to a third-party host."""
    body = client.get("/").text

    assert "//fonts.googleapis.com" not in body
    assert "//cdn" not in body
    assert body.count("http://") == 0


def test_mcp_endpoint_still_challenges_instead_of_serving_html(client):
    """The page is for browsers at /; /mcp stays a protected machine surface."""
    response = client.get("/mcp", headers={"Accept": "text/html"})

    assert response.status_code == 401
    assert "Bearer" in response.headers["www-authenticate"]


def test_health_and_discovery_are_untouched(client):
    assert client.get("/health").json()["status"] == "ok"
    assert (
        client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"]
        == RESOURCE
    )
