"""Operator-coordinated real GitHub head change during publication.

Not a webhook test. Uses a new PostgreSQL schema and temporary public bare mirror;
retains the schema for signed-checkpoint auditing. Pauses before the final head read; never simulates a GitHub response.
"""
import argparse
import json
from pathlib import Path
import os
import subprocess
import tempfile
import time
import uuid

import sqlalchemy as sa
from alembic import command
from reposhield.server.admin import migration_config
from reposhield.server.config import ServerConfig
from reposhield.server.durable import DurableStore
from reposhield.server.process_worker import ProcessWorker
from reposhield.server.github_service import GitHubService
from reposhield.server.github_app import AppClient, load_config, fetch_public
from reposhield.server.schema_v5 import checks
from reposhield.server.schema_v1 import tasks
from reposhield.server.identities import Identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trusted', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    runtime = json.loads((args.trusted/'local-runtime.json').read_text())
    app = load_config(args.trusted/'github-app-config.json', [str(Path.cwd())])
    client = AppClient(app, [str(Path.cwd())]); token = client.installation_token()
    pr = client.pull(1, token)
    if pr['state'] != 'open':
        raise RuntimeError('Fixture requires open PR #1')
    schema = 'rs_live_race_' + uuid.uuid4().hex
    root = sa.create_engine(runtime['REPOSHIELD_DATABASE_URL'])
    with root.begin() as conn: conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    url = sa.engine.make_url(runtime['REPOSHIELD_DATABASE_URL']).update_query_dict(
        {'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    report = {'schema':schema,'trigger':'explicit operator rerun, not a webhook',
              'pr':pr['html_url'],'head':pr['head']['sha'],'schema_retained_for_audit':True}
    store = DurableStore(url)
    try:
        command.upgrade(migration_config(url), 'head')
        cfg = ServerConfig(database_url=url, github_app_config_file=str(args.trusted/'github-app-config.json'),
            signing_key_file=runtime['REPOSHIELD_SIGNING_KEY_FILE'], signing_key_id=runtime['REPOSHIELD_SIGNING_KEY_ID'],
            verification_keys_file=runtime['REPOSHIELD_VERIFICATION_KEYS_FILE'])
        with tempfile.TemporaryDirectory(prefix='reposhield-fault-mirror-') as scratch:
            boundary = Path(scratch).resolve(); mirror = boundary/'mirror.git'; parked = boundary/'parked.git'
            env = {k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','TEMP','TMP','USERPROFILE')}
            env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0')
            subprocess.run(['git','-c','credential.helper=','clone','--bare',
                'https://github.com/'+app.full_name+'.git',str(mirror)],env=env,capture_output=True,check=True,timeout=60)
            store.register_repository(repository_id=app.repository_id,tenant_id='demo',name=app.full_name,
                                      path=str(mirror),base_sha=pr['base']['sha'])
            service=GitHubService(store,cfg); service.onboard()
            merge_base=fetch_public(store.repository(app.repository_id),app,pr)
            source=dict(installation_id=app.installation_id,remote_repository_id=app.remote_repository_id,
                pr_number=1,base_tip=pr['base']['sha'],head_sha=pr['head']['sha'],merge_base=merge_base,
                execution_tree=pr['head']['sha'],strategy='head-only-require-up-to-date-branch')
            job=store.enqueue(app.repository_id,pr['head']['sha'],'operator-race-rehearsal',source_context=source)
            with store.engine.begin() as conn:
                conn.execute(checks.insert().values(attempt_id=job['attempt_id'],repository_id=app.repository_id,
                    pr_number=1,head_sha=pr['head']['sha'],base_sha=pr['base']['sha']))
            worker = ProcessWorker(store)
            for _ in range(8):
                if not worker.run_once(): break
            attempt = store.get_attempt(job['attempt_id'])
            if attempt['state'] != 'completed' or attempt['result']['verdict'] != 'PASS':
                raise RuntimeError('Race fixture must have genuine completed PASS')
            original_pull = service.client.pull
            reads = []
            def gated_pull(number, scoped_token):
                reads.append(number)
                if len(reads) == 2:
                    ready = dict(pr=1, old_head=pr['head']['sha'], attempt_id=job['attempt_id'],
                                 signal='Commit to PR #1 now, then confirm; publication paused before final real API read')
                    (out/'ready.json').write_text(json.dumps(ready, indent=2))
                    print(json.dumps(ready), flush=True)
                    deadline = time.monotonic() + 900
                    while not (out/'resume').exists():
                        if time.monotonic() >= deadline: raise RuntimeError('Operator signal timed out; no success publication')
                        time.sleep(1)
                actual = original_pull(number, scoped_token)
                if len(reads) == 2 and actual['head']['sha'] == pr['head']['sha']:
                    raise RuntimeError('No real head change observed; no success publication')
                return actual
            service.client.pull = gated_pull
            service.run_once(publishing=True)
            with store.engine.connect() as conn:
                row = dict(conn.execute(sa.select(checks).where(checks.c.attempt_id==job['attempt_id'])).mappings().one())
            if row['state'] != 'obsolete': raise RuntimeError('Publication did not become obsolete')
            remote = client.call('GET', f'/repos/{app.full_name}/check-runs/{row["check_id"]}', token)
            if remote.get('conclusion') is not None: raise RuntimeError('Stale Check acquired a conclusion')
            current = client.pull(1, token)
            if remote['head_sha'] != pr['head']['sha'] or current['head']['sha'] == pr['head']['sha']:
                raise RuntimeError('Unexpected Check binding')
            # Close only this rehearsal-created queued Check on the old SHA.
            client.call('PATCH', f'/repos/{app.full_name}/check-runs/{row["check_id"]}', token,
                {'status':'completed','conclusion':'cancelled','output':{
                    'title':'Stale-head acceptance rehearsal cancelled',
                    'summary':'Real head changed before final publication read; no success was published.'}})
            report.update(passed=True, old_head=pr['head']['sha'], new_head=current['head']['sha'],
                attempt_id=job['attempt_id'], genuine_verdict=attempt['result']['verdict'],
                check_id=row['check_id'], check_url=remote['html_url'], state=row['state'],
                conclusion_before_cleanup=remote.get('conclusion'), cleanup_conclusion='cancelled',
                checkpoint_id=row['checkpoint_id'], api_responses_simulated=False,
                final_read_race_validated=True, after_final_read_race_validated=False)
            print(json.dumps(report), flush=True)
    finally:
        store.engine.dispose(); root.dispose()
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    try: main()
    except Exception as error:
        print('Live rehearsal failed: '+type(error).__name__)
        raise SystemExit(1)
