"""Local synthetic evaluation; never accepts arbitrary repository inputs.

Runs authored fixtures in the development subprocess backend, NOT an isolation
acceptance test. Production credentials and the live demo database are not used.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reposhield.demo import build_demo, _git, _write, _read
from reposhield.engine import VerifyOptions, verify
from reposhield.action_policy import Resource, Scope, evaluate
from reposhield.contracts import ActionRequest
from benchmark.bench import bench_graph

EXPECTED = {
    'pr/safe-refactor': 'PASS', 'pr/analytics-leak': 'BLOCK',
    'pr/transitive-leak': 'BLOCK', 'pr/secret-and-workflow': 'BLOCK',
    'pr/weakened-tests': 'REVIEW_REQUIRED', 'pr/real-bug': 'BLOCK',
    'pr/policy-tamper': 'BLOCK', 'pr/docs-only': 'PASS',
    'pr/new-dependency': 'REVIEW_REQUIRED', 'pr/prod-config': 'REVIEW_REQUIRED',
}
EXTRA = [
    ('guide', 'docs/guide.md', '# Synthetic guide\n', 'PASS'),
    ('license', 'LICENSE', 'Synthetic evaluation license notice\n', 'PASS'),
    ('workflow-text', '.github/workflows/denied.txt', 'Harmless forbidden-path fixture\n', 'BLOCK'),
    ('env-file', '.env', 'DEMO=synthetic\n', 'BLOCK'),
    ('pem-path', 'example.pem', 'Not a private key\n', 'BLOCK'),
    ('invalid-python', 'auth/login.py', '\ndef broken(:\n', 'BLOCK'),
    ('auth-comment', 'auth/login.py', '\n# Synthetic auth edit\n', 'PASS'),
    ('api-comment', 'api/routes.py', '\n# Synthetic API edit\n', 'PASS'),
    ('production-note', 'config/production/note.txt', 'Synthetic config note\n', 'REVIEW_REQUIRED'),
    ('requirements-note', 'requirements.txt', '\n# Dependency manifest review fixture\n', 'REVIEW_REQUIRED'),
]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def controls():
    scope = Scope(actions=('READ_FILE', 'APPLY_PATCH', 'RUN_TESTS'),
                  paths=('src/app.py', 'tests/test_app.py', 'docs/guide.md'),
                  profiles=('isolated-python',))
    resource = Resource(resource_id='source', tenant_id='tenant', repository_id='repo',
                        workspace_revision='sha256:' + 'a'*64, policy_epoch=1,
                        administrator=scope, repository=scope, sessions={'agent': scope})
    def patch(path):
        return {'action_type': 'APPLY_PATCH', 'patch': f'--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n'}
    read = {'action_type': 'READ_FILE', 'path': 'src/app.py'}
    cases = [('read', read, {}, 'ALLOW'), ('patch', patch('src/app.py'), {}, 'ALLOW'),
             ('tests', {'action_type': 'RUN_TESTS', 'test_paths': ['tests/test_app.py'], 'profile': 'isolated-python'}, {}, 'ALLOW'),
             ('docs-review', patch('docs/guide.md'), {}, 'REVIEW_REQUIRED')]
    cases += [(kind.lower(), {'action_type': kind, 'resource_id': 'production'}, {}, 'DENY')
              for kind in ('DATABASE_OPERATION', 'NETWORK_REQUEST', 'EXECUTE_COMMAND')]
    cases += [(name, {'action_type': 'READ_FILE', 'path': path}, {}, 'DENY')
              for name, path in [('traversal', '../secret'), ('absolute', '/etc/passwd'),
                                 ('policy', '.reposhield.yml'), ('outside-scope', 'src/other.py')]]
    cases += [('stale-revision', read, {'workspace_revision': 'sha256:' + 'b'*64}, 'DENY'),
              ('wrong-tenant', read, {'tenant_id': 'other'}, 'DENY'),
              ('extra-capability', read, {'requested_capabilities': ['production']}, 'DENY'),
              ('malformed-patch', {'action_type': 'APPLY_PATCH', 'patch': 'not a patch'}, {}, 'DENY')]
    rows = []
    for name, action, overrides, expected in cases:
        fields = dict(schema_version=2, tenant_id='tenant', repository_id='repo',
                      session_id='session', workspace_revision=resource.workspace_revision,
                      action=action)
        req = ActionRequest.model_validate({**fields, **overrides})
        samples = []
        for _ in range(100):
            start = time.perf_counter_ns()
            result = evaluate(req, resource, scope)
            samples.append(time.perf_counter_ns() - start)
        rows.append({'name': name, 'request': req.model_dump(mode='json'), 'expected': expected,
                     'result': result, 'matched': result['decision'] == expected,
                     'policy_latency_ns': samples, 'median_ns': statistics.median(samples)})
    return {'scope': scope.model_dump(mode='json'), 'resource': resource.model_dump(mode='json'),
            'cases': rows, 'boundary': 'pure policy only; no token claim or execution'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    # Fresh output required: preserve previous runs and all operator data.
    out.mkdir(parents=True, exist_ok=False)
    repo = out / 'synthetic-repository'
    build_demo(str(repo))
    expected = dict(EXPECTED)
    for name, path, addition, verdict in EXTRA:
        branch = 'eval/' + name
        _git(str(repo), 'checkout', '-q', '-b', branch, 'main')
        old = _read(str(repo), path) if (repo / path).exists() else ''
        _write(str(repo), path, old + addition)
        _git(str(repo), 'add', '-A')
        _git(str(repo), 'commit', '-q', '-m', name)
        expected[branch] = verdict
    _git(str(repo), 'checkout', '-q', 'main')
    rows = []
    for branch, target in expected.items():
        start = time.perf_counter()
        result = verify(VerifyOptions(repo=str(repo), base='main', head=branch,
                                      sandbox='subprocess', force=True))
        name = branch.replace('/', '-')
        write_json(out / (name + '.json'), result)
        patch = subprocess.check_output(['git', '-C', str(repo), 'diff', 'main', branch])
        (out / (name + '.patch')).write_bytes(patch)
        row = {'branch': branch, 'expected': target, 'actual': result['verdict'],
               'matched': target == result['verdict'], 'elapsed_s': time.perf_counter()-start,
               'tests': result['tests'], 'plan': result['plan'], 'graph': result['graph'],
               'patch_sha256': hashlib.sha256(patch).hexdigest()}
        rows.append(row)
        print(f"{branch}: {result['verdict']} (expected {target})", flush=True)
        write_json(out / 'changes.json', rows)
    action = controls()
    write_json(out / 'controls.json', action)
    graph = [bench_graph(n_files=200, n_changed=5, seed=seed) for seed in (7, 11, 19)]
    write_json(out / 'graph.json', graph)
    write_json(out / 'environment.json', {'python': sys.version, 'platform': platform.platform(),
        'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'execution': 'trusted authored synthetic fixtures; development subprocess; not isolation proof'})
    passed = sum(r['matched'] for r in rows)
    policy_passed = sum(r['matched'] for r in action['cases'])
    write_json(out / 'summary.json', {'change_matches': passed, 'change_total': len(rows),
        'policy_matches': policy_passed, 'policy_total': len(action['cases']),
        'graph_equivalence': all(r['identical_to_full_rebuild'] for r in graph),
        'pending': ['full-versus-selected execution timings', 'durable scheduler and signed authorization overhead',
                    'dedicated Linux acceptance', 'remaining GitHub acceptance']})
    return 0 if passed == len(rows) and policy_passed == len(action['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
