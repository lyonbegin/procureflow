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
            "runner_environment": "github-hosted",
        }
        wf=payload.get("workflow_ref")
        event=payload.get("event_name")
        bridge_qa=(
            "lyonbegin/procureflow/.github/workflows/"
            "hitel-integration-bridge-live-qa.yml@refs/heads/main"
        )
        allowed=(wf==WORKFLOW_REF and event in ("push","workflow_dispatch","schedule"))
        allowed=allowed or (wf==bridge_qa and event in ("push","workflow_dispatch"))
        pairing_workflow=(
            "lyonbegin/procureflow/.github/workflows/"
            "hitel-integration-bridge-live-qa.yml@refs/heads/main"
        )
        allowed=allowed or (wf==pairing_workflow and
                           event in ("push","workflow_dispatch"))
        return all(payload.get(k)==v for k,v in must_equal.items()) and allowed
    except (PyJWTError, ValueError, TypeError, OSError, TimeoutError):
        return False
    except Exception:
        # Never let a JWKS HTTP failure, invalid claim type or parser failure
        # convert an untrusted token into device authorization.
        return False


FILE_SCENARIO_AUDIENCE = "urn:lyonbegin:procureflow:hitel-file-scenario-api"
FILE_SCENARIO_WORKFLOW_REF = (
    "lyonbegin/procureflow/.github/workflows/"
    "hitel-file-scenarios-via-api.yml@refs/heads/main"
)


def verify_file_scenario_identity(raw_token: str) -> bool:
    """Authorize only the main-branch manual synthetic file test workflow.

    This identity is deliberately NOT the general relay worker identity:
    it cannot access private user rooms, credentials or ordinary file APIs.
    """
    if not isinstance(raw_token, str) or not 50 <= len(raw_token) <= 8192:
        return False
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(raw_token)
        payload = jwt.decode(
            raw_token, signing_key.key, algorithms=["RS256"],
            audience=FILE_SCENARIO_AUDIENCE, issuer=ISSUER, leeway=15,
            options={"require": ["iss", "aud", "iat", "nbf", "exp", "sub"]},
        )
        must_equal = {
            "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID,
            "repository_owner_id": OWNER_ID,
            "ref": "refs/heads/main",
            "workflow_ref": FILE_SCENARIO_WORKFLOW_REF,
            "runner_environment": "github-hosted",
        }
        # Only the dedicated pinned workflow, on main, may publish synthetic
        # results; a one-shot push of that workflow file is permitted.
        return (all(payload.get(k) == v for k, v in must_equal.items())
                and payload.get("event_name") in ("push","workflow_dispatch"))
    except (PyJWTError, ValueError, TypeError, OSError, TimeoutError):
        return False
    except Exception:
        return False

BRIDGE_QA_WORKFLOW_REF = (
    "lyonbegin/procureflow/.github/workflows/"
    "hitel-integration-bridge-live-qa.yml@refs/heads/main"
)


def verify_bridge_qa_identity(raw_token: str) -> bool:
    """Only a main-branch, GitHub-hosted QA workflow may run fixed test chat.

    No external application receives or supplies this identity. Browser session
    ownership is NOT granted by a test workflow.
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
            "ref": "refs/heads/main",
            "workflow_ref": BRIDGE_QA_WORKFLOW_REF,
            "runner_environment": "github-hosted",
        }
        return (all(payload.get(k) == v for k,v in must_equal.items())
                and payload.get("event_name") in ("push","workflow_dispatch"))
    except (PyJWTError, ValueError, TypeError, OSError, TimeoutError):
        return False
    except Exception:
        return False


PAIRING_WORKFLOW_REF = (
    "lyonbegin/procureflow/.github/workflows/"
    "hitel-integration-bridge-live-qa.yml@refs/heads/main"
)


def verify_pairing_identity(raw_token: str) -> bool:
    """Only signed main branch GitHub Actions account-pairing may bind a profile.

    It must separately verify a real active ChatGPT HTTPS session against the
    encrypted registered Chrome profile, and provide an unexpired browser
    challenge. A GitHub token alone cannot choose the browser owner.
    """
    if not isinstance(raw_token, str) or not 50<=len(raw_token)<=8192:
        return False
    try:
        key=_jwk_client().get_signing_key_from_jwt(raw_token)
        payload=jwt.decode(
            raw_token,key.key,algorithms=["RS256"],
            audience=AUDIENCE,issuer=ISSUER,leeway=15,
            options={"require":["iss","aud","iat","nbf","exp","sub"]},
        )
        exact={
          "repository":REPOSITORY,"repository_id":REPOSITORY_ID,
          "repository_owner_id":OWNER_ID,"ref":"refs/heads/main",
          "workflow_ref":PAIRING_WORKFLOW_REF,
          "runner_environment":"github-hosted",
        }
        return (all(payload.get(k)==v for k,v in exact.items())
                and payload.get("event_name") in ("push","workflow_dispatch"))
    except (PyJWTError,ValueError,TypeError,OSError,TimeoutError):
        return False
    except Exception:
        return False


ISOLATED_WORKER_WORKFLOW_REF = (
    "lyonbegin/procureflow/.github/workflows/"
    "hitel-isolated-chrome-worker.yml@refs/heads/main"
)


def verify_isolated_worker_identity(raw_token: str) -> dict | None:
    """OIDC-bound task worker identity; never authorize the shared /ws route.

    The worker's task id comes from a fixed GitHub workflow input. The relay
    independently restricts it to a server-known task, and fences the
    connection by the verified run_id and monotonically increasing generation.
    """
    if not isinstance(raw_token,str) or not 50<=len(raw_token)<=8192:
        return None
    try:
        key=_jwk_client().get_signing_key_from_jwt(raw_token)
        claims=jwt.decode(raw_token,key.key,algorithms=["RS256"],
            audience=AUDIENCE,issuer=ISSUER,leeway=15,
            options={"require":["iss","aud","iat","nbf","exp","sub"]})
        expected={
            "repository":REPOSITORY,
            "repository_id":REPOSITORY_ID,
            "repository_owner_id":OWNER_ID,
            "ref":REF,
            "runner_environment":"github-hosted",
            "workflow_ref":ISOLATED_WORKER_WORKFLOW_REF,
            "event_name":"workflow_dispatch",
        }
        run_id=claims.get("run_id")
        if (not all(claims.get(k)==v for k,v in expected.items())
                or not isinstance(run_id,str) or not run_id.isdecimal()):
            return None
        return {"run_id":run_id}
    except (PyJWTError,ValueError,TypeError,OSError,TimeoutError):
        return None
    except Exception:
        return None


TASK_PRODUCER_AUDIENCE = "urn:lyonbegin:procureflow:hitel-isolated-task-submit"
# Source ownership is fixed to the user-authorized GitHub repositories. A
# public HTTP caller cannot submit expensive ChatGPT requests or impersonate
# another task without an exact, signed GitHub Actions workflow identity.
TASK_PRODUCER_WORKFLOWS = {
    "stock-a": {
        "repository":"lyonbegin/autonomous-investor-backend",
        "repository_id":"1427623630",
        "ref":"refs/heads/main",
        "workflow_ref":(
            "lyonbegin/autonomous-investor-backend/.github/workflows/"
            "stock-a-task-isolated-chrome.yml@refs/heads/main"),
        "event_name":"workflow_dispatch",
    },
    "stock-tv": {
        "repository":"lyonbegin/autonomous-investor-backend",
        "repository_id":"1427623630",
        "ref":"refs/heads/main",
        "workflow_ref":(
            "lyonbegin/autonomous-investor-backend/.github/workflows/"
            "stock-tv-task-isolated-research.yml@refs/heads/main"),
        "event_name":"workflow_dispatch",
    },
    "scribd-18109": {
        "repository":"lyonbegin/hitel-scribd-runner",
        "repository_id":"1455284203",
        "ref":"refs/heads/main",
        "workflow_ref":(
            "lyonbegin/hitel-scribd-runner/.github/workflows/"
            "hitel-public-ai-corpus.yml@refs/heads/main"),
        "event_name":"workflow_dispatch",
    },
}


def verify_isolated_task_producer(raw_token: str, task_id: str) -> bool:
    """Prove an exact authorized project workflow owns this Railway task."""
    expected=TASK_PRODUCER_WORKFLOWS.get(task_id)
    if not expected or not isinstance(raw_token,str) or not 50<=len(raw_token)<=8192:
        return False
    try:
        key=_jwk_client().get_signing_key_from_jwt(raw_token)
        payload=jwt.decode(raw_token,key.key,algorithms=["RS256"],
            audience=TASK_PRODUCER_AUDIENCE,issuer=ISSUER,leeway=15,
            options={"require":["iss","aud","iat","nbf","exp","sub"]})
        return (all(payload.get(k)==v for k,v in expected.items())
                and payload.get("repository_owner_id")==OWNER_ID
                and payload.get("runner_environment")=="github-hosted")
    except (PyJWTError,ValueError,TypeError,OSError,TimeoutError):
        return False
    except Exception:
        return False
