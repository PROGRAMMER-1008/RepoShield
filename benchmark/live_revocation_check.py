"""Reversible operator acceptance test; suspends then restores the demo App.

Uses the prior isolated fault schema, never creates a synthetic webhook. Requires
the configured App installation to be initially active; cleanup always unsuspends.
"""
import argparse
import json
from pathlib import Path
import time
import sqlalchemy as sa
from reposhield.server.config import ServerConfig
from reposhield.server.durable import DurableStore
from reposhield.server.github_service import GitHubService
from reposhield.server.github_app import AccessRevoked
from reposhield.server.schema_v1 import repositories, tasks, attempts
from reposhield.server.schema_v5 import checks


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trusted',type=Path,required=True); p.add_argument('--fault-evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    if a.output.exists(): raise ValueError('Use fresh output')
    runtime=json.loads((a.trusted/'local-runtime.json').read_text())
    fault=json.loads(a.fault_evidence.read_text()); schema=fault['schema']
    if not schema.startswith('rs_live_fault_') or not schema[14:].isalnum(): raise ValueError('Unexpected schema')
    url=sa.engine.make_url(runtime['REPOSHIELD_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
    def config(db):
        return ServerConfig(database_url=db,github_app_config_file=str(a.trusted/'github-app-config.json'),
            signing_key_file=runtime['REPOSHIELD_SIGNING_KEY_FILE'],signing_key_id=runtime['REPOSHIELD_SIGNING_KEY_ID'],
            verification_keys_file=runtime['REPOSHIELD_VERIFICATION_KEYS_FILE'])
    store=DurableStore(url); svc=GitHubService(store,config(url)); client=svc.client; app=svc.config
    path=f'/app/installations/{app.installation_id}/suspended'
    initial=client.call('GET',f'/app/installations/{app.installation_id}',client.jwt())
    if initial.get('suspended_at') is not None: raise RuntimeError('Already suspended; refusing to change operator state')
    token=client.installation_token(); pr=client.pull(3,token)
    with store.engine.begin() as c:
        c.execute(repositories.update().where(repositories.c.id==app.repository_id).values(path=str(a.trusted/'repoguard-demo.git')))
    svc.onboard()
    job=store.enqueue(app.repository_id,pr['head']['sha'],'revocation-rehearsal',rerun_key='suspension-acceptance')
    with store.engine.begin() as c:
        c.execute(checks.insert().values(attempt_id=job['attempt_id'],repository_id=app.repository_id,pr_number=3,
            head_sha=pr['head']['sha'],base_sha=pr['base']['sha']))
    result={'schema':schema,'attempt_id':job['attempt_id'],'real_installation_suspension':False}
    restore_needed=False
    try:
        # Set before request, so an ambiguous response still triggers restoration.
        restore_needed=True
        client.call('PUT',path,client.jwt())
        result['real_installation_suspension']=True
        try: client.installation_token()
        except AccessRevoked: result['fresh_installation_access_denied']=True
        else: raise RuntimeError('Suspended installation still obtained access')
        svc.run_once(publishing=True)
        with store.engine.connect() as c:
            result['binding_disabled']=not svc.binding(c)['enabled']
            row=dict(c.execute(sa.select(checks).where(checks.c.attempt_id==job['attempt_id'])).mappings().one())
        if not result['binding_disabled']: raise RuntimeError('Revocation did not disable binding')
        if store.claim('revoked-worker') is not None: raise RuntimeError('Revoked job was claimed')
        result.update(claim_denied=True,remote_check_created=row['check_id'] is not None,
                      publication_state=row['state'],publication_error=row['error'])
        if result['remote_check_created']: raise RuntimeError('Revoked publication created a Check')
    finally:
        if restore_needed:
            client.call('DELETE',path,client.jwt())
            client.installation_token()
            svc.onboard()
            live=DurableStore(runtime['REPOSHIELD_DATABASE_URL'])
            try:
                time.sleep(3)
                GitHubService(live,config(runtime['REPOSHIELD_DATABASE_URL'])).onboard()
            finally: live.engine.dispose()
            result['access_restored_and_explicitly_onboarded']=True
        with store.engine.begin() as c:
            c.execute(tasks.update().where(tasks.c.attempt_id==job['attempt_id'],tasks.c.state=='queued').values(state='cancelled'))
            c.execute(attempts.update().where(attempts.c.id==job['attempt_id']).values(state='cancelled'))
            c.execute(checks.update().where(checks.c.attempt_id==job['attempt_id']).values(state='obsolete'))
        store.engine.dispose()
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))


if __name__=='__main__':
    try: main()
    except Exception as error:
        print('Revocation rehearsal failed: '+type(error).__name__)
        raise SystemExit(1)
