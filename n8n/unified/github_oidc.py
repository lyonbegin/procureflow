"""Verify only GitHub Actions OIDC bearer tokens for public9 callbacks/files.

No static callback token is stored in GitHub. The signing keys are fetched
from the official GitHub OIDC issuer; the repository AND workflow ref must
match our pinned control plane. An arbitrary public webhook cannot spoof runs.
"""
from __future__ import annotations
import os,threading,time
from urllib.request import urlopen
import json
import jwt
from jwt.algorithms import RSAAlgorithm

ISSUER="https://token.actions.githubusercontent.com"
JWKS_URL="https://token.actions.githubusercontent.com/.well-known/jwks"
AUDIENCE="procureflow-action-worker"
REPO="lyonbegin/procureflow"
WORKFLOW="procureflow-node.yml"
ALLOWED_REFS=(
 "refs/heads/main",
 "refs/heads/feature/procureflow-unified-studio-20261107",
)
_CACHE=None
_STAMP=0
_LOCK=threading.RLock()

class GitHubOIDCError(ValueError):
    pass

def verify(header):
    if not isinstance(header,str) or not header.startswith("Bearer "):
        raise GitHubOIDCError("GITHUB_OIDC_BEARER_REQUIRED")
    token=header[7:].strip()
    if len(token)>10000:raise GitHubOIDCError("INVALID_GITHUB_OIDC_LENGTH")
    try:
        hdr=jwt.get_unverified_header(token)
        if hdr.get("alg")!="RS256" or not hdr.get("kid"):
            raise GitHubOIDCError("INVALID_GITHUB_OIDC_HEADER")
        with _LOCK:
            global _CACHE,_STAMP
            if not _CACHE or time.time()-_STAMP>1800:
                with urlopen(JWKS_URL,timeout=8) as response:
                    source=json.loads(response.read(200000))
                _CACHE=source.get("keys") or []
                _STAMP=time.time()
            key=next((k for k in _CACHE if k.get("kid")==hdr["kid"]),None)
        if not key:raise GitHubOIDCError("GITHUB_OIDC_UNTRUSTED_KEY")
        public=RSAAlgorithm.from_jwk(json.dumps(key))
        claims=jwt.decode(token,public,algorithms=["RS256"],
                          audience=AUDIENCE,issuer=ISSUER,leeway=15,
                          options={"require":["exp","iat","iss","aud","sub"]})
        if claims.get("repository")!=REPO or claims.get("repository_owner")!="lyonbegin":
            raise GitHubOIDCError("GITHUB_OIDC_WRONG_REPOSITORY")
        ref=claims.get("ref")
        if ref not in ALLOWED_REFS:
            raise GitHubOIDCError("GITHUB_OIDC_WRONG_REF")
        flow_ref=str(claims.get("workflow_ref") or "")
        if flow_ref!=f"{REPO}/.github/workflows/{WORKFLOW}@{ref}":
            raise GitHubOIDCError("GITHUB_OIDC_WRONG_WORKFLOW")
        if not str(claims.get("run_id") or "").isdigit():
            raise GitHubOIDCError("GITHUB_OIDC_RUN_ID_REQUIRED")
        return claims
    except GitHubOIDCError:raise
    except Exception as e:
        raise GitHubOIDCError("GITHUB_OIDC_NOT_VERIFIED") from e
