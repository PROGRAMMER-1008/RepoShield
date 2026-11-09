"""Deterministic verdict aggregation. No scores, no LLM, UNKNOWN never becomes PASS."""
from __future__ import annotations

from .models import Finding


def aggregate(findings: list[Finding]) -> tuple[str, str]:
    blocks = [f for f in findings if f.effect == "BLOCK"]
    reviews = [f for f in findings if f.effect == "REVIEW"]
    if blocks:
        verdict = "BLOCK"
        lead = blocks[0]
        extra = len(blocks) - 1
    elif reviews:
        verdict = "REVIEW_REQUIRED"
        lead = reviews[0]
        extra = len(reviews) - 1
    else:
        return "PASS", "All mandatory checks passed."
    summary = f"{lead.rule_id}: {lead.message}" + (f" (+{extra} more finding{'s' if extra > 1 else ''})" if extra else "")
    return verdict, summary
