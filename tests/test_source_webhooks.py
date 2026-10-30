import hashlib
import hmac
import unittest

from ontology_software_factory.source_webhooks import SourceWebhookError, verify_source_webhook


class SourceWebhookTests(unittest.TestCase):
    def test_github_signature_and_repository_are_verified(self):
        raw = b'{"repository":{"html_url":"https://github.com/acme/orders"},"ref":"refs/heads/main"}'
        secret = "test-secret"
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        result = verify_source_webhook(
            "github",
            {"type": "github", "url": "https://github.com/acme/orders", "webhookSecretEnv": "HOOK_SECRET"},
            {"X-Hub-Signature-256": signature, "X-GitHub-Event": "push", "X-GitHub-Delivery": "delivery-1"},
            raw,
            {"repository": {"html_url": "https://github.com/acme/orders"}},
            environ={"HOOK_SECRET": secret},
        )
        self.assertEqual(result, {"deliveryId": "delivery-1", "eventType": "push"})

    def test_github_rejects_invalid_signature(self):
        with self.assertRaises(SourceWebhookError):
            verify_source_webhook(
                "github",
                {"type": "github", "url": "https://github.com/acme/orders", "webhookSecretEnv": "HOOK_SECRET"},
                {"X-Hub-Signature-256": "sha256=" + "0" * 64, "X-GitHub-Event": "push", "X-GitHub-Delivery": "d1"},
                b"{}",
                {"repository": {"html_url": "https://github.com/acme/orders"}},
                environ={"HOOK_SECRET": "secret"},
            )

    def test_webhook_cannot_trigger_another_repository(self):
        raw = b"{}"
        secret = "secret"
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with self.assertRaises(SourceWebhookError):
            verify_source_webhook(
                "github",
                {"type": "github", "url": "https://github.com/acme/orders", "webhookSecretEnv": "HOOK_SECRET"},
                {"X-Hub-Signature-256": signature, "X-GitHub-Event": "push", "X-GitHub-Delivery": "d1"},
                raw,
                {"repository": {"html_url": "https://github.com/acme/payroll"}},
                environ={"HOOK_SECRET": secret},
            )

    def test_gitlab_token_and_project_identity_are_verified(self):
        result = verify_source_webhook(
            "gitlab",
            {"type": "gitlab", "url": "https://gitlab.com/acme/platform/orders", "webhookSecretEnv": "GL_HOOK"},
            {"X-Gitlab-Token": "secret", "X-Gitlab-Event": "Push Hook", "X-Gitlab-Event-UUID": "uuid-1"},
            b"{}",
            {"project": {"web_url": "https://gitlab.com/acme/platform/orders"}},
            environ={"GL_HOOK": "secret"},
        )
        self.assertEqual(result["deliveryId"], "uuid-1")

    def test_unconfigured_secret_fails_closed(self):
        with self.assertRaises(SourceWebhookError):
            verify_source_webhook(
                "github",
                {"type": "github", "url": "https://github.com/acme/orders"},
                {},
                b"{}",
                {},
                environ={},
            )


if __name__ == "__main__":
    unittest.main()
