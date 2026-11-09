"""Operator-triggered real GitHub failure rehearsal on an already-blocked demo PR.

Not a webhook test. Uses a new PostgreSQL schema and temporary public bare mirror;
retains the schema for signed-checkpoint auditing. Creates one real failed Check.
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
    pr = client.pull(3, token)
    if pr['state'] != 'open' or pr.get('mergeable_state') != 'blocked':
        raise RuntimeError('Fixture requires open, already blocked PR #3')
    schema = 'rs_live_fault_' + uuid.uuid4().hex
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
                pr_number=3,base_tip=pr['base']['sha'],head_sha=pr['head']['sha'],merge_base=merge_base,
                execution_tree=pr['head']['sha'],strategy='head-only-require-up-to-date-branch')
            job=store.enqueue(app.repository_id,pr['head']['sha'],'operator-failure-rehearsal',source_context=source)
            with store.engine.begin() as conn:
                conn.execute(checks.insert().values(attempt_id=job['attempt_id'],repository_id=app.repository_id,
                    pr_number=3,head_sha=pr['head']['sha'],base_sha=pr['base']['sha']))
            if not mirror.resolve().is_relative_to(boundary) or not parked.resolve().is_relative_to(boundary):
                raise RuntimeError('Invalid disposable mirror boundary')
            mirror.rename(parked)
            try:
                worker=ProcessWorker(store)
                for _ in range(5):
                    # Accelerate only retry scheduling; leave failure/result logic untouched.
                    with store.engine.begin() as conn:
                        conn.execute(tasks.update().where(tasks.c.attempt_id==job['attempt_id'],tasks.c.state=='queued')
                                     .values(available_at=sa.func.now()))
                    worker.run_once()
                    if store.get_attempt(job['attempt_id'])['state']=='failed-infrastructure': break
            finally:
                parked.rename(mirror)
            attempt=store.get_attempt(job['attempt_id'])
            if attempt['state']!='failed-infrastructure' or attempt['result'] is not None:
                raise RuntimeError('Real snapshot failure did not fail closed')
            service.run_once(publishing=True)
            with store.engine.connect() as conn:
                row=dict(conn.execute(sa.select(checks).where(checks.c.attempt_id==job['attempt_id'])).mappings().one())
            if row['state']!='published': raise RuntimeError('Failure Check did not publish')
            remote=client.call('GET',f'/repos/{app.full_name}/check-runs/{row["check_id"]}',token)
            if remote['conclusion']!='failure' or remote['output']['title']!='Infrastructure failure':
                raise RuntimeError('Unexpected live Check result')
            admin=Identity(id='operator',role='administrator',tenant_id='demo',repository_ids=[app.repository_id],token_sha256='0'*64)
            replay=service.evidence.replay(row['checkpoint_id'],admin)
            if not replay['authenticated']: raise RuntimeError('Failure evidence not authenticated')
            time.sleep(2)
            current=client.pull(3,token)
            report.update(attempt_id=job['attempt_id'],state=attempt['state'],result=attempt['result'],
                tasks=[{k:t.get(k) for k in ('stage','state','tries','error')} for t in attempt['tasks']],
                check_id=row['check_id'],check_url=remote['html_url'],conclusion=remote['conclusion'],
                title=remote['output']['title'],checkpoint_id=row['checkpoint_id'],authenticated=True,
                mergeable_state=current.get('mergeable_state'),retry_backoff_accelerated=True,
                live_mirror_untouched=True,merge_attempted=False)
            print(json.dumps(report))
    finally:
        store.engine.dispose(); root.dispose()
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    try: main()
    except Exception as error:
        print('Live rehearsal failed: '+type(error).__name__)
        raise SystemExit(1)
