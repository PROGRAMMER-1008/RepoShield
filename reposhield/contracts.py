"""Versioned wire contracts, independent of authorization and execution adapters.

Parsing a request grants no authority. The action policy evaluates authenticated requests;
the legacy command gateway must never consume these as execution permission.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RESULT_SCHEMA_VERSION = 2
ACTION_SCHEMA_VERSION = 2

VerificationVerdict = Literal["PASS", "BLOCK", "REVIEW_REQUIRED"]
ActionDecision = Literal["ALLOW", "DENY", "REVIEW_REQUIRED"]
ExecutionState = Literal["queued", "running", "completed", "failed-infrastructure",
                         "cancelled", "unknown-outcome"]
ProductMode = Literal["VERIFICATION ONLY", "CONTROLLED SESSION", "DEVELOPMENT EXECUTION"]
Identifier = Annotated[str, Field(min_length=1, max_length=256)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadFile(Contract):
    action_type: Literal["READ_FILE"]
    path: Identifier
    max_bytes: int = Field(default=65536, strict=True, gt=0, le=1048576)


class ApplyPatch(Contract):
    action_type: Literal["APPLY_PATCH"]
    patch: str = Field(min_length=1, max_length=1048576)


class RunTests(Contract):
    action_type: Literal["RUN_TESTS"]
    test_paths: tuple[Identifier, ...] = Field(min_length=1, max_length=1000)
    profile: Identifier


class UnsupportedAction(Contract):
    # Explicitly represent requests that the first release must deny.
    action_type: Literal["NETWORK_REQUEST", "DATABASE_OPERATION", "EXECUTE_COMMAND"]
    resource_id: Identifier


class ActionRequest(Contract):
    schema_version: Literal[2]
    tenant_id: Identifier
    repository_id: Identifier
    session_id: Identifier
    workspace_revision: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    action: Annotated[ReadFile | ApplyPatch | RunTests | UnsupportedAction,
                      Field(discriminator="action_type")]
    requested_capabilities: tuple[Identifier, ...] = Field(default=(), max_length=32)


class VerificationReceipt(Contract):
    schema_version: Literal[2]
    run_id: Identifier
    attempt_id: Identifier
    input_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    verdict: VerificationVerdict
    execution_state: ExecutionState
    mode: ProductMode

    @model_validator(mode="after")
    def success_requires_completion(self):
        if self.verdict == "PASS" and self.execution_state != "completed":
            raise ValueError("PASS requires completed evidence evaluation")
        return self
