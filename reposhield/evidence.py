"""Public-key-only evidence verification. Never executes replayed code or actions."""
import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature

DOMAIN = b"reposhield:evidence:v1\x00"
MAX_BUNDLE = 768 * 1024
MAX_EVENTS = 2000
ZERO = "0" * 64
OMIT = {"stdout", "stderr", "junit", "patch", "content_base64", "password", "credential",
        "token", "authorization", "private_key", "secret", "environment", "env"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def redact(value, depth=0):
    """Bounded retained view, not a promise to recognize every possible secret."""
    if depth > 32:
        raise ValueError("evidence nesting limit")
    if isinstance(value, dict):
        return {str(k): ("[OMITTED]" if str(k).lower() in OMIT or
                        any(s in str(k).lower() for s in ("password", "secret", "private_key", "credential"))
                        else redact(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [\s\S]*?PRIVATE KEY-----[\s\S]*?-----END [\s\S]*?PRIVATE KEY-----", "[REDACTED KEY]", value)
        value = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?i)(password|token|secret|credential)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]", value)
        value = re.sub(r"(\w+://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)
        return value[:4096] + ("[TRUNCATED]" if len(value) > 4096 else "")
    if value is None or type(value) in (int, float, bool):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise ValueError("unsupported evidence value")


def assemble(context, artifacts, history):
    if not history or len(history) > MAX_EVENTS:
        raise ValueError("missing or excessive event evidence")
    head, chain = ZERO, []
    for index, entry in enumerate(history):
        record = {"index": index, "previous": head, "entry": entry}
        head = digest(record)
        chain.append({**record, "hash": head})
    manifest = {"version": 1, "context": context, "artifacts": {k: digest(v) for k, v in artifacts.items()},
                "event_count": len(chain), "event_head": head, "redaction_version": 1}
    bundle = {"manifest": manifest, "artifacts": artifacts, "events": chain}
    if len(canonical(bundle)) > MAX_BUNDLE:
        raise ValueError("evidence bundle limit")
    return bundle


def signing_bytes(key_id, manifest):
    return DOMAIN + canonical({"key_id": key_id, "manifest": manifest})


def verify_bundle(bundle, keys, checkpoint, expected_context):
    """Checkpoint and expected context MUST come from the trusted database/caller."""
    try:
        if len(canonical(bundle)) > MAX_BUNDLE or set(bundle) != {"manifest", "artifacts", "events", "key_id", "signature"}:
            raise ValueError()
        manifest = bundle["manifest"]
        if (manifest["version"] != 1 or manifest["redaction_version"] != 1
                or manifest["context"] != expected_context or checkpoint["context"] != expected_context):
            raise ValueError()
        keys[bundle["key_id"]].verify(base64.b64decode(bundle["signature"], validate=True),
                                     signing_bytes(bundle["key_id"], manifest))
        if {k: digest(v) for k, v in bundle["artifacts"].items()} != manifest["artifacts"]:
            raise ValueError()
        chain = bundle["events"]
        if not chain or len(chain) > MAX_EVENTS or len(chain) != manifest["event_count"]:
            raise ValueError()
        head = ZERO
        for index, row in enumerate(chain):
            record = {"index": index, "previous": head, "entry": row["entry"]}
            if row != {**record, "hash": digest(record)}:
                raise ValueError()
            head = row["hash"]
        if (head != manifest["event_head"] or head != checkpoint["event_head"]
                or len(chain) != checkpoint["event_count"] or digest(bundle) != checkpoint["bundle_digest"]):
            raise ValueError()
    except (KeyError, TypeError, ValueError, InvalidSignature, RecursionError):
        raise ValueError("evidence authentication failed") from None
    return {"authenticated": True, "context": expected_context,
            "artifacts": bundle["artifacts"], "history": [row["entry"] for row in chain],
            "cache_eligible": False, "cache_reason": "cache reuse disabled pending validated verification execution"}
