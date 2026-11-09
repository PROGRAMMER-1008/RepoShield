"""Opt-in real PostgreSQL timings; isolated random schemas, no execution.

Run with REPOSHIELD_TEST_DATABASE_URL and REPOSHIELD_EVAL_OUTPUT set.
Uses existing regression fixtures, including fresh external ephemeral signing keys.
"""
import json
import os
from pathlib import Path
import time

import pytest
from fastapi import HTTPException
from tests.conftest import demo_repo
from tests.test_durable import pg, registered, enqueue
from tests.test_action_policy import service, actor
from tests.test_authorization import signed, claim


def save(name, rows):
    root = Path(os.environ['REPOSHIELD_EVAL_OUTPUT'])
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    with target.open('x', encoding='utf-8') as stream:
        json.dump(rows, stream, indent=2)


def timed(fn):
    start = time.perf_counter_ns()
    value = fn()
    return value, time.perf_counter_ns() - start


def test_scheduler_admission_and_first_claim(registered, demo_repo):
    rows = []
    for index in range(20):
        result, admission = timed(lambda: enqueue(registered, demo_repo, rerun_key=f'eval-{index}'))
        task, acquisition = timed(lambda: registered.claim('evaluation-worker'))
        assert task['attempt_id'] == result['attempt_id'] and task['stage'] == 'snapshot'
        rows.append({'index': index, 'enqueue_ns': admission, 'claim_ns': acquisition})
    save('scheduler.json', rows)


def test_signed_authorization_issue_claim_and_replay(signed):
    rows = []
    for index in range(20):
        decision, policy_ns = timed(lambda: signed['policy'].authorize(signed['body'], actor()))
        assert decision['decision'] == 'ALLOW'
        token, issue_ns = timed(lambda: signed['issuer'].issue(decision['id'], actor()))
        execution, claim_ns = timed(lambda: claim(signed, token=token))
        assert execution['state'] == 'unknown-outcome' and not execution['execution_enabled']
        with pytest.raises(HTTPException) as failure:
            claim(signed, token=token)
        assert failure.value.status_code == 409
        rows.append({'index': index, 'authorize_ns': policy_ns, 'issue_ns': issue_ns,
                     'claim_ns': claim_ns, 'replay_status': failure.value.status_code})
    save('authorization.json', rows)
