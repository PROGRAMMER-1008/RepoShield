"""Replay a historical GitHub payload into a fresh local intake schema.

Uses real GitHub reads and public Git fetches. Operator re-signs the retrieved
payload; this does not claim a new GitHub webhook delivery or an in-flight race.
No remote Check is created, and no branch or pull request is modified.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import sqlalchemy as sa
from alembic import command
from reposhield.server.admin import migration_config
from reposhield.server.config import ServerConfig
from reposhield.server.durable import DurableStore
from reposhield.server.github_app import AppClient, load_config
from reposhield.server.github_service import GitHubService
from reposhield.server.schema_v5 import checks, deliveries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trusted', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delivery-id', type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'operator-re-signed historical payload, first local intake; real GitHub API and Git',
              'live_inflight_race_validated': False, 'remote_mutations': False}
    root = store = None
    schema = 'rs_stale_' + uuid.uuid4().hex
    try:
        runtime = json.loads((args.trusted / 'local-runtime.json').read_text())
        config = load_config(args.trusted / 'github-app-config.json', [str(Path.cwd())])
        client = AppClient(config, [str(Path.cwd())])
        token = client.installation_token()
        historical = client.call('GET', f'/app/hook/deliveries/{args.delivery_id}', client.jwt())
        payload = historical['request']['payload']
        if isinstance(payload, str): payload = json.loads(payload)
        number = payload['pull_request']['number']
        old = payload['pull_request']['head']['sha']
        current = client.pull(number, token)
        assert current['state'] == 'open' and current['head']['sha'] != old
        assert payload['repository']['id'] == config.remote_repository_id
        report.update(pr=number, historical_head=old, current_head=current['head']['sha'],
                      historical_delivery_id=args.delivery_id)
        root = sa.create_engine(runtime['REPOSHIELD_DATABASE_URL'])
        with root.begin() as c: c.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        url = sa.engine.make_url(runtime['REPOSHIELD_DATABASE_URL']).update_query_dict(
            {'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
        store = DurableStore(url)
        command.upgrade(migration_config(url), 'head')
        with tempfile.TemporaryDirectory(prefix='rs-stale-mirror-') as directory:
            mirror = Path(directory) / 'mirror.git'
            env = {k: v for k, v in os.environ.items() if k.upper() in ('PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE')}
            env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
            subprocess.run(['git', '-c', 'credential.helper=', 'clone', '--bare',
                            'https://github.com/' + config.full_name + '.git', str(mirror)],
                           env=env, capture_output=True, check=True, timeout=60)
            store.register_repository(repository_id=config.repository_id, tenant_id='demo',
                                      name=config.full_name, path=str(mirror), base_sha=current['base']['sha'])
            service = GitHubService(store, ServerConfig(database_url=url,
                github_app_config_file=str(args.trusted / 'github-app-config.json')))
            service.onboard()
            raw = json.dumps(payload, separators=(',', ':')).encode()
            secret = Path(config.webhook_secret_file).read_text().strip().encode()
            signature = 'sha256=' + hmac.new(secret, raw, hashlib.sha256).hexdigest()
            receipt = service.receive('first-arrival-' + uuid.uuid4().hex, 'pull_request', signature, raw)
            assert receipt == {'duplicate': False, 'state': 'pending'}
            assert service.run_once()
            with store.engine.connect() as c:
                delivery = c.execute(sa.select(deliveries)).mappings().one()
                check = c.execute(sa.select(checks)).mappings().one()
            assert delivery['state'] == 'processed', delivery['error']
            assert check['head_sha'] == current['head']['sha']
            report['first_arrival_used_current_head'] = True
            # A genuine historical head must become obsolete before remote creation.
            job = store.enqueue(config.repository_id, old, 'stale-acceptance')
            with store.engine.begin() as c:
                c.execute(checks.insert().values(attempt_id=job['attempt_id'], repository_id=config.repository_id,
                    pr_number=number, head_sha=old, base_sha=current['base']['sha']))
                row = c.execute(sa.select(checks).where(checks.c.attempt_id == job['attempt_id'])).mappings().one()
                service._publish(c, row, token)
                row = c.execute(sa.select(checks).where(checks.c.attempt_id == job['attempt_id'])).mappings().one()
                assert row['state'] == 'obsolete' and row['check_id'] is None
            report['historical_publication_obsolete_without_remote_check'] = True
            after = client.pull(number, token)
            assert after['head']['sha'] == current['head']['sha'], 'PR changed during observation'
            report['passed'] = True
    except Exception as error:
        report.update(passed=False, error_type=type(error).__name__)
    finally:
        if store: store.engine.dispose()
        if root:
            with root.begin() as c: c.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            root.dispose()
            report['disposable_schema_removed'] = True
        (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
