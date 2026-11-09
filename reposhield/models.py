from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Finding:
    """One piece of evidence produced by a check or policy rule.

    result : PASS | FAIL | REVIEW_REQUIRED | UNKNOWN | NOT_APPLICABLE | PENDING
    effect : how it influences the verdict (NONE | INFO | REVIEW | BLOCK) -- derived, never LLM-decided.
    """
    source: str
    rule_id: str
    rule_type: str
    result: str
    severity: str = "medium"
    message: str = ""
    evidence: list = field(default_factory=list)
    on_fail: str | None = None

    @property
    def effect(self) -> str:
        r = self.result
        if r in ("PASS", "NOT_APPLICABLE"):
            return "NONE"
        if r in ("REVIEW_REQUIRED", "UNKNOWN", "PENDING"):
            return "REVIEW"          # lack of evidence is never PASS
        if r == "FAIL":
            if self.rule_type == "required_test" and (self.on_fail == "info" or
                                                       (not self.on_fail and self.severity == "low")):
                return "REVIEW"     # a mandatory requirement cannot be informational
            if self.on_fail:
                return {"block": "BLOCK", "review": "REVIEW", "info": "INFO"}[self.on_fail]
            return {"critical": "BLOCK", "high": "BLOCK", "medium": "REVIEW", "low": "INFO"}.get(self.severity, "REVIEW")
        return "REVIEW"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["effect"] = self.effect
        return d
