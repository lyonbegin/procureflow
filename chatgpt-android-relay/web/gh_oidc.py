"""Verify GitHub-hosted Actions as a second authenticated relay device.

No GitHub/Railway shared password or repository secret is needed.
The legacy DEVICE_TOKEN route is unchanged. A GitHub OIDC JWT is accepted
ONLY for the exact ChatGPT Web2API relay worker workflow and the main ref.
"""
import functools
import os

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = "https://token.actions.githubusercontent.com/.well-known/jwks"
AUDIENCE = "urn:lyonbegin:procureflow:chatgpt-relay:device"
REPOSITORY_ID = "1426590470"
OWNER_ID = "92076336"
REPOSITORY = "lyonbegin/procureflow"
REF = "refs/heads/main"
WORKFLOW_REF = (
    "lyonbegin/procureflow/.github/workflows/"
    "chatgpt-web2api-relay-worker.yml@refs/heads/main"
)


@functools.lru_cache(maxsize=1)
def _jwk_client():
    return PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300, timeout=8)


def verify_worker_identity(raw_token: str) -> bool:
    """Fail closed for every unexpected issuer/claim/signature or network error.

    Return only boolean; caller must never print raw_token or decoded claims.
    """
    if not isinstance(raw_token, str) or not 50 <= len(raw_token) <= 8192:
        return False
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(raw_token)
        payload = jwt.decode(
            raw_token, signing_key.key, algorithms=["RS256"],
            audience=AUDIENCE, issuer=ISSUER, leeway=15,
            options={"require": ["iss", "aud", "iat", "nbf", "exp", "sub"]},
        )
        must_equal = {
            "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID,
            "repository_owner_id": OWNER_ID,
            "ref": REF,
            "workflow_ref": WORKFLOW_REF,
            "runner_environment": "github-hosted",
        }
        return (all(payload.get(k) == v for k, v in must_equal.items())
                and payload.get("event_name") in ("push", "workflow_dispatch"))
    except (PyJWTError, ValueError, TypeError, OSError, TimeoutError):
        return False
    except Exception:
        # Never let a JWKS HTTP failure, invalid claim type or parser failure
        # convert an untrusted token into device authorization.
        return False
