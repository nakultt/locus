"""
Webhook signature verification.

The /webhooks/github endpoint cannot use a JWT -- GitHub has no user token. The
HMAC signature over the raw body IS the authentication, so these tests guard the
only thing standing between the internet and a queued job.
"""

import hashlib
import hmac

from app.routers.webhooks import verify_github_signature

SECRET = "sup3rsecret"
BODY = b'{"action":"opened","repository":{"full_name":"acme/api"}}'


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_accepts_valid_signature():
    assert verify_github_signature(BODY, sign(BODY), SECRET) is True


def test_rejects_tampered_body():
    tampered = BODY.replace(b"opened", b"closed")
    assert verify_github_signature(tampered, sign(BODY), SECRET) is False


def test_rejects_wrong_secret():
    assert verify_github_signature(BODY, sign(BODY, "wrong"), SECRET) is False


def test_rejects_missing_signature():
    assert verify_github_signature(BODY, "", SECRET) is False


def test_rejects_signature_without_algorithm_prefix():
    bare = sign(BODY).removeprefix("sha256=")
    assert verify_github_signature(BODY, bare, SECRET) is False


def test_rejects_sha1_prefix():
    """GitHub's legacy X-Hub-Signature (SHA-1) must not be accepted."""
    sha1 = "sha1=" + hmac.new(SECRET.encode(), BODY, hashlib.sha1).hexdigest()
    assert verify_github_signature(BODY, sha1, SECRET) is False


def test_rejects_empty_body_with_stale_signature():
    assert verify_github_signature(b"", sign(BODY), SECRET) is False
