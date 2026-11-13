"""Isolated cryptographic regressions: no network, no secrets, no Railway."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gh_oidc


class TestGithubOidcWorkerIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = cls.private.public_key()

    def token(self, **overrides):
        now = int(time.time())
        payload = {
            "iss": gh_oidc.ISSUER,
            "aud": gh_oidc.AUDIENCE,
            "sub": "repo:lyonbegin/procureflow:ref:refs/heads/main",
            "iat": now,
            "nbf": now - 2,
            "exp": now + 180,
            "repository": gh_oidc.REPOSITORY,
            "repository_id": gh_oidc.REPOSITORY_ID,
            "repository_owner_id": gh_oidc.OWNER_ID,
            "workflow_ref": gh_oidc.WORKFLOW_REF,
            "ref": gh_oidc.REF,
            "runner_environment": "github-hosted",
            "event_name": "push",
        }
        payload.update(overrides)
        return jwt.encode(payload, self.private, algorithm="RS256", headers={"kid":"test"})

    def verify(self, token):
        client=SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=self.public))
        with patch.object(gh_oidc, "_jwk_client", return_value=client):
            return gh_oidc.verify_worker_identity(token)

    def test_exact_trusted_workflow(self):
        self.assertTrue(self.verify(self.token()))

    def test_exact_scheduled_worker_is_accepted(self):
        self.assertTrue(self.verify(self.token(event_name="schedule")))

    def test_scheduled_wrong_workflow_still_rejected(self):
        self.assertFalse(self.verify(self.token(
            event_name="schedule", workflow_ref="lyonbegin/procureflow/.github/workflows/other.yml@refs/heads/main")))

    def test_wrong_audience(self):
        self.assertFalse(self.verify(self.token(aud="something-else")))

    def test_wrong_issuer(self):
        self.assertFalse(self.verify(self.token(iss="https://fake.example")))

    def test_wrong_repository_and_owner(self):
        self.assertFalse(self.verify(self.token(repository_id="123")))
        self.assertFalse(self.verify(self.token(repository_owner_id="444")))

    def test_other_workflow_rejected(self):
        self.assertFalse(self.verify(self.token(workflow_ref=gh_oidc.WORKFLOW_REF.replace("relay-worker","verify-session"))))

    def test_untrusted_ref_and_runner(self):
        self.assertFalse(self.verify(self.token(ref="refs/heads/untrusted")))
        self.assertFalse(self.verify(self.token(runner_environment="self-hosted")))

    def test_pull_request_event_rejected(self):
        self.assertFalse(self.verify(self.token(event_name="pull_request")))

    def test_expired_and_future_tokens(self):
        now=int(time.time())
        self.assertFalse(self.verify(self.token(exp=now-300)))
        self.assertFalse(self.verify(self.token(nbf=now+300)))

    def test_bad_signature_and_bad_input(self):
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        payload=jwt.decode(self.token(),self.public,algorithms=["RS256"],audience=gh_oidc.AUDIENCE)
        tampered=jwt.encode(payload,other,algorithm="RS256",headers={"kid":"test"})
        self.assertFalse(self.verify(tampered))
        self.assertFalse(self.verify("garbage"))
        self.assertFalse(self.verify(""))

    def test_no_github_public_key_no_authorization(self):
        with patch.object(gh_oidc, "_jwk_client",side_effect=RuntimeError("offline")):
            self.assertFalse(gh_oidc.verify_worker_identity(self.token()))


if __name__ == "__main__":
    unittest.main()
