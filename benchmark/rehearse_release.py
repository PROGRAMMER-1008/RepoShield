"""Exercise an installed wheel with disposable PostgreSQL backup/restore/restart.

Requires local Docker and a cached pinned image. Creates and removes only its own
randomly named container. No live database, platform credentials or network pulls.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid
import base64
import shutil
import tempfile

import sqlalchemy as sa
import psycopg
from alembic import command
import reposhield
from reposhield.demo import build_demo
from reposhield.gitutil import resolve
from reposhield.server.admin import migration_config
from reposhield.server.durable import DurableStore, STAGES
from reposhield.server.process_worker import ProcessWorker
from reposhield.server.evidence_service import EvidenceService
from reposhield.server.config import ServerConfig
from reposhield.server.identities import Identity
from reposhield.snapshots import SnapshotStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException

IMAGE = 'postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3'


def docker(*args, data=None, env=None):
    result = subprocess.run(['docker', *args], input=data, capture_output=True,
                            timeout=90, env=env)
    if result.returncode:
        raise RuntimeError('Docker operation failed: ' + args[0])
    return result.stdout


def digest_database(engine):
    with engine.connect() as conn:
        names = sa.inspect(conn).get_table_names(schema='public')
        result = {}
        for name in sorted(names):
            quoted = engine.dialect.identifier_preparer.quote(name)
            rows = sorted(conn.execute(sa.text(f'SELECT row_to_json(t)::text FROM {quoted} t')).scalars())
            result[name] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--installed-root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=55434, help='Unused loopback port; Docker refuses an occupied binding')
    parser.add_argument('--signed-evidence', action='store_true', help='Also restore synthetic external keys/snapshot and authenticate database evidence')
    args = parser.parse_args()
    installed = args.installed_root.resolve()
    if not Path(reposhield.__file__).resolve().is_relative_to(installed):
        raise RuntimeError('Rehearsal must import the installed wheel, not workspace source')
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    name = 'reposhield-rehearsal-' + uuid.uuid4().hex[:12]
    password = secrets.token_hex(24)
    env = {**os.environ, 'POSTGRES_PASSWORD': password}
    created = False
    external = tempfile.TemporaryDirectory(prefix='reposhield-recovery-keys-') if args.signed_evidence else None
    report = {'installed_module': str(Path(reposhield.__file__).resolve()), 'image': IMAGE,
              'rounds': [], 'scope': 'same-host installed-wheel static DAG and database recovery; not full isolated product demo'}
    try:
        docker('image', 'inspect', IMAGE)
        docker('run', '-d', '--pull=never', '--name', name, '--memory=512m', '--cpus=1',
               '-p', f'127.0.0.1:{args.port}:5432', '-e', 'POSTGRES_PASSWORD', IMAGE, env=env)
        created = True
        port = docker('port', name, '5432/tcp').decode().strip().split(':')[-1]
        def ready():
            for _ in range(30):
                check = subprocess.run(['docker', 'exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'], capture_output=True, timeout=10)
                if check.returncode == 0:
                    try:
                        with psycopg.connect(host='127.0.0.1', port=int(port), user='postgres',
                                             password=password, dbname='postgres', connect_timeout=2):
                            return
                    except psycopg.OperationalError:
                        pass
                time.sleep(1)
            raise RuntimeError('Disposable PostgreSQL startup timed out')
        ready()
        def url(database):
            return f'postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/{database}'
        for index in (1, 2):
            cfg = None
            if external:
                trusted = Path(external.name) / f'original-{index}'
                trusted.mkdir()
                key = Ed25519PrivateKey.generate()
                (trusted / 'signer.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
                (trusted / 'public.json').write_text(json.dumps({'recovery': base64.b64encode(key.public_key().public_bytes_raw()).decode()}))
                revision = SnapshotStore(trusted / 'snapshots').put({'src/app.py': b'VALUE = 1\n'})
                cfg = ServerConfig(signing_key_file=str(trusted/'signer.pem'), signing_key_id='recovery',
                                   verification_keys_file=str(trusted/'public.json'))
                admin = Identity(id='recovery-admin', role='administrator', tenant_id='demo',
                                 repository_ids=['demo'], token_sha256='0'*64)
            source, restored = f'source{index}', f'restored{index}'
            for db in (source, restored):
                docker('exec', name, 'createdb', '-U', 'postgres', db)
            command.upgrade(migration_config(url(source)), 'head')
            repo = out / f'synthetic-{index}'; build_demo(str(repo))
            store = DurableStore(url(source)); store.check_schema()
            store.register_repository(repository_id='demo', tenant_id='demo', name='synthetic',
                                      path=str(repo), base_sha=resolve(str(repo), 'main'))
            runs = []
            for branch, expected in [('pr/docs-only','PASS'), ('pr/analytics-leak','BLOCK'), ('pr/safe-refactor','REVIEW_REQUIRED')]:
                job = store.enqueue('demo', resolve(str(repo), branch), 'rehearsal')
                worker = ProcessWorker(store)
                for _ in STAGES:
                    if not worker.run_once(): raise RuntimeError('Expected durable stage missing')
                attempt = store.get_attempt(job['attempt_id'])
                if attempt['state'] != 'completed' or attempt['result']['verdict'] != expected:
                    raise RuntimeError('Unexpected real verification result')
                row = {'branch':branch,'verdict':expected,'attempt_id':job['attempt_id']}
                if cfg:
                    row['checkpoint_id'] = EvidenceService(store, cfg).seal('attempt', job['attempt_id'], admin)['checkpoint_id']
                runs.append(row)
            before = digest_database(store.engine)
            backup = docker('exec', name, 'pg_dump', '-U', 'postgres', '-Fc', source)
            (out / f'round-{index}.dump').write_bytes(backup)
            docker('exec', '-i', name, 'pg_restore', '-U', 'postgres', '--no-owner', '--exit-on-error', '-d', restored, data=backup)
            other = DurableStore(url(restored)); other.check_schema()
            after = digest_database(other.engine)
            if before != after: raise RuntimeError('Restore table content mismatch')
            if cfg:
                recovered = Path(external.name) / f'recovered-{index}'
                shutil.copytree(trusted, recovered)
                if SnapshotStore(recovered/'snapshots').get(revision) != {'src/app.py': b'VALUE = 1\n'}:
                    raise RuntimeError('Recovered snapshot mismatch')
                restored_key = serialization.load_pem_private_key((recovered/'signer.pem').read_bytes(), password=None)
                challenge = b'Synthetic recovery signing challenge'
                key.public_key().verify(restored_key.sign(challenge), challenge)
                # Replay is explicitly public-key-only, with no signer configured.
                replay_cfg = ServerConfig(verification_keys_file=str(recovered/'public.json'))
                for row in runs:
                    replay = EvidenceService(other, replay_cfg).replay(row['checkpoint_id'], admin)
                    if not replay['authenticated'] or replay['artifacts']['result']['verdict'] != row['verdict']:
                        raise RuntimeError('Recovered evidence did not authenticate')
                    row['restored_authenticated'] = True
                wrong = recovered/'wrong-public.json'
                wrong.write_text(json.dumps({'recovery': base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()}))
                try:
                    EvidenceService(other, ServerConfig(verification_keys_file=str(wrong))).replay(runs[0]['checkpoint_id'], admin)
                except HTTPException as failure:
                    if failure.status_code != 409: raise
                else:
                    raise RuntimeError('Wrong restored key unexpectedly authenticated')
            store.engine.dispose(); other.engine.dispose()
            docker('restart', name); ready()
            other = DurableStore(url(restored)); other.check_schema()
            restarted = digest_database(other.engine)
            if cfg:
                for row in runs:
                    if not EvidenceService(other, replay_cfg).replay(row['checkpoint_id'], admin)['authenticated']:
                        raise RuntimeError('Evidence failed after database restart')
                    row['restart_authenticated'] = True
            other.engine.dispose()
            if after != restarted: raise RuntimeError('Restart table content mismatch')
            report['rounds'].append({'round':index,'runs':runs,'tables':before,
                'backup_sha256':hashlib.sha256(backup).hexdigest(),'restore_equal':True,'restart_equal':True,
                'synthetic_key_snapshot_restore':bool(cfg),'wrong_key_rejected':bool(cfg)})
            print(f'Round {index}: three real verdicts, backup/restore and restart equality passed', flush=True)
    finally:
        if external:
            external.cleanup()
            report['synthetic_external_keys_removed'] = True
        if created:
            docker('rm', '-f', '-v', name)
            report['disposable_container_removed'] = True
        (out / 'rehearsal.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Rehearsal failed: ' + type(error).__name__)
        raise SystemExit(1)
