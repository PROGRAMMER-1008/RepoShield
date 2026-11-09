"""Coordinator-only private key loading. No fallback or automatic key generation."""
import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..authorization import SignedAuthorization, signing_bytes


class DecisionSigner:
    def __init__(self, private_path, key_id, workspace_roots):
        path = Path(private_path).resolve(strict=True)
        if any(path.is_relative_to(Path(root).resolve()) for root in workspace_roots):
            raise ValueError("private signing key must be outside source and agent workspaces")
        with path.open("rb") as f:
            raw = f.read(16385)
        if len(raw) > 16384:
            raise ValueError("key file too large")
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Ed25519 private key required")
        self._key, self.key_id = key, key_id

    def sign(self, payload):
        token = SignedAuthorization(key_id=self.key_id, payload=payload, signature="A" * 86)
        signature = base64.urlsafe_b64encode(self._key.sign(signing_bytes(token))).rstrip(b"=").decode()
        return token.model_copy(update={"signature": signature})

    def sign_evidence(self, bundle):
        from ..evidence import signing_bytes, canonical, MAX_BUNDLE
        value = {**bundle, "key_id": self.key_id,
                 "signature": base64.b64encode(self._key.sign(signing_bytes(self.key_id, bundle["manifest"]))).decode()}
        if len(canonical(value)) > MAX_BUNDLE:
            raise ValueError("evidence bundle limit")
        return value
