"""Time two fresh local technical rehearsals; not a narrated UI demo or video.

Requires explicitly configured disposable PostgreSQL test schemas and cached
Docker runner image. Uses synthetic repositories, keys and protected data.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


CASES = [
    'tests/test_e2e.py::test_scenario_verdicts',
    'tests/test_product_ui.py::test_required_tests_stay_review_required_in_real_worker_ui',
    'tests/test_authorization.py::test_real_signature_idempotent_issue_and_one_shot_claim',
    'tests/test_protected_database.py::test_real_protected_shop_workflow_and_bypass',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('REPOSHIELD_TEST_DATABASE_URL') or not os.environ.get('REPOSHIELD_TEST_RUNNER_IMAGE'):
        parser.error('Explicit test database and cached runner image are required')
    if os.environ.get('REPOSHIELD_TEST_PROTECTED_DATABASE') != '1':
        parser.error('Explicit protected synthetic database opt-in is required')
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'two-mode automated technical rehearsal on Docker Desktop; not a full narrated demo',
              'dedicated_linux_acceptance': 'pending', 'cases': CASES, 'rounds': []}
    try:
        for number in (1, 2):
            folder = out / f'round-{number}'
            folder.mkdir()
            env = {**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
                   'REPOSHIELD_TEST_EVIDENCE_DIR': str(folder)}
            started = time.perf_counter()
            process = subprocess.run([sys.executable, '-m', 'pytest', *CASES, '-q', '-ra',
                '--basetemp=' + str(folder / 'temporary'), '--junitxml=' + str(folder / 'tests.xml')],
                cwd=root, env=env, capture_output=True, timeout=600)
            elapsed = time.perf_counter() - started
            result = {'round': number, 'seconds': round(elapsed, 2), 'exit_code': process.returncode}
            report['rounds'].append(result)
            if process.returncode != 0:
                raise RuntimeError('Rehearsal tests failed; inspect local XML, no success claimed')
            suite = ET.parse(folder / 'tests.xml').getroot().find('testsuite')
            result.update(tests=int(suite.attrib['tests']), failures=int(suite.attrib['failures']),
                          errors=int(suite.attrib['errors']), skipped=int(suite.attrib['skipped']))
            if result['tests'] != 13 or any(result[k] for k in ('failures', 'errors', 'skipped')):
                raise RuntimeError('Missing or unsuccessful mandatory rehearsal case')
            protected = json.loads((folder / 'protected-database.json').read_text())
            if protected['database_unchanged'] is not True or protected['policy_denial']['decision'] != 'DENY':
                raise RuntimeError('Missing protected-resource evidence')
            result.update(protected_database_unchanged=True, passed=True)
            print(json.dumps(result), flush=True)
        report['passed'] = True
    except Exception as error:
        report.update(passed=False, error_type=type(error).__name__)
    finally:
        (out / 'rehearsal.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
