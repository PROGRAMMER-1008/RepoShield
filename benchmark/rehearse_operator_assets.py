"""Offline recovery rehearsal of actual operator assets outside agent workspaces.

Creates private temporary backup/restore directories inside the trusted folder.
Never exports credentials, connects to GitHub, or modifies working configuration.
This is same-host recovery evidence, not an encrypted/off-site backup solution.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from reposhield.server.browser_auth import BrowserConfig
from reposhield.server.github_app import load_config


ASSETS = ('evidence-signing.pem', 'verification-keys.json', 'github-app.pem',
          'github-app-config.json', 'github-webhook-secret.txt', 'oauth-secret.txt',
          'ui-config.json', 'identities.json', 'operator-api-token.txt',
          'local-runtime.json', 'start-demo.ps1')


def command(argv, env=None):
    result = subprocess.run(argv, env=env, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError('External recovery command failed')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trusted', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    trusted = args.trusted.resolve(strict=True)
    if trusted.is_relative_to(source) or source.is_relative_to(trusted):
        parser.error('Trusted assets must be outside the source workspace')
    if os.name != 'nt': parser.error('This rehearsal requires Windows ACL support')
    args.output.mkdir(parents=True, exist_ok=False)
    scratch = trusted / ('recovery-rehearsal-' + uuid.uuid4().hex)
    report = {'scope': 'offline same-host actual operator asset restore; no live cutover',
              'live_configuration_modified': False, 'credentials_exported_to_workspace': False,
              'network_used': False, 'permanent_backup_created': False}
    original = {}
    try:
        scratch.mkdir()
        # Restrict the scratch tree before writing any credential bytes.
        sid = command(['powershell.exe', '-NoProfile', '-Command',
            '[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value']).decode().strip()
        if not sid.startswith('S-1-'): raise RuntimeError('Invalid owner SID')
        command(['icacls', str(scratch), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F'])
        backup, restored = scratch / 'backup', scratch / 'restored'
        backup.mkdir(); restored.mkdir()
        for name in ASSETS:
            path = trusted / name
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(trusted):
                raise RuntimeError('Asset escaped trusted directory')
            original[name] = hashlib.sha256(path.read_bytes()).digest()
            shutil.copy2(path, backup / name)
            shutil.copy2(backup / name, restored / name)
            if hashlib.sha256((restored / name).read_bytes()).digest() != original[name]:
                raise RuntimeError('Restored asset mismatch')
        report['restored_files_equal'] = list(ASSETS)
        runtime = json.loads((restored / 'local-runtime.json').read_text())
        public = json.loads((restored / 'verification-keys.json').read_text())
        evidence_key = serialization.load_pem_private_key((restored / 'evidence-signing.pem').read_bytes(), None)
        verifier = Ed25519PublicKey.from_public_bytes(base64.b64decode(public[runtime['REPOSHIELD_SIGNING_KEY_ID']]))
        challenge = b'RepoShield operator recovery challenge:' + os.urandom(32)
        verifier.verify(evidence_key.sign(challenge), challenge)
        app_key = serialization.load_pem_private_key((restored / 'github-app.pem').read_bytes(), None)
        original_app_key = serialization.load_pem_private_key((trusted / 'github-app.pem').read_bytes(), None)
        original_app_key.public_key().verify(app_key.sign(challenge, padding.PKCS1v15(), hashes.SHA256()),
                                            challenge, padding.PKCS1v15(), hashes.SHA256())
        identities = json.loads((restored / 'identities.json').read_text())
        token_digest = hashlib.sha256((restored / 'operator-api-token.txt').read_text().strip().encode()).hexdigest()
        if not any(i['token_sha256'] == token_digest for i in identities):
            raise RuntimeError('Restored operator identity mismatch')
        for name, fields in [('github-app-config.json', ('private_key_file', 'webhook_secret_file')),
                             ('ui-config.json', ('client_secret_file',))]:
            config = json.loads((restored / name).read_text())
            for field in fields:
                original_path = Path(config[field]).resolve(strict=True)
                if original_path.parent != trusted or original_path.name not in ASSETS:
                    raise RuntimeError('Configuration references an unbacked asset')
                config[field] = str(restored / original_path.name)
            (restored / name).write_text(json.dumps(config))
        load_config(restored / 'github-app-config.json', [str(source)])
        BrowserConfig.model_validate_json((restored / 'ui-config.json').read_text())
        report.update(restored_signing_key_verified=True, restored_app_key_verified=True,
                      restored_operator_identity_verified=True, restored_app_ui_config_valid=True)
        env = {k: v for k, v in os.environ.items() if k.upper() in ('PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
        mirror = trusted / 'repoguard-demo.git'
        if mirror.is_symlink() or not mirror.resolve(strict=True).is_relative_to(trusted):
            raise RuntimeError('Mirror escaped trusted directory')
        refs = command(['git', '-C', str(mirror), 'show-ref'], env)
        bundle = backup / 'mirror.bundle'
        command(['git', '-C', str(mirror), 'bundle', 'create', str(bundle), '--all'], env)
        command(['git', '-c', 'credential.helper=', 'clone', '--mirror', str(bundle), str(restored / 'mirror.git')], env)
        if command(['git', '-C', str(restored / 'mirror.git'), 'show-ref'], env) != refs:
            raise RuntimeError('Restored mirror refs differ')
        command(['git', '-C', str(restored / 'mirror.git'), 'fsck', '--full'], env)
        if command(['git', '-C', str(mirror), 'show-ref'], env) != refs:
            raise RuntimeError('Source mirror changed during rehearsal')
        report.update(restored_mirror_refs_equal=True, restored_mirror_fsck_passed=True,
                      source_mirror_refs_unchanged=True, passed=True)
    except Exception as error:
        report.update(passed=False, error_type=type(error).__name__)
    finally:
        unchanged = all(hashlib.sha256((trusted / name).read_bytes()).digest() == digest
                        for name, digest in original.items())
        report['source_assets_unchanged'] = unchanged
        if not unchanged: report['passed'] = False
        # Resolve and bound the exact unique scratch directory before recursive removal.
        if scratch.exists():
            if scratch.resolve().parent != trusted or not scratch.name.startswith('recovery-rehearsal-'):
                raise RuntimeError('Unsafe cleanup target')
            shutil.rmtree(scratch, onerror=lambda function, path, exc: (os.chmod(path, 0o700), function(path)))
        report['temporary_secret_copies_removed'] = not scratch.exists()
        (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
