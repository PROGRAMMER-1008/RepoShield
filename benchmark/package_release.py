"""Build an explicit-allowlist local candidate zip; never traverses trusted runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--offline', action='store_true', help='Include the Windows CPython 3.10 dependency wheelhouse and lock')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = [root / 'requirements-release-windows-py310.txt', root / 'README.md',
             root / 'compose.rs2.yml', root / '.rs2-release/wheels/reposhield-0.2.1-py3-none-any.whl']
    files += sorted((root / 'docs').glob('*.md'))
    files += sorted((root / 'benchmark').glob('*.py'))
    files += sorted((root / 'tests').glob('*.py'))
    files += [root / 'runner' / name for name in
              ('.dockerignore', 'Dockerfile', 'Dockerfile.project', 'Dockerfile.restricted',
               'entry.py', 'pytest_entry.py', 'pytest.ini')]
    files += [root / 'docs/evidence/rs2-11/metrics.json', root / 'docs/evidence/rs2-12/wheel.json',
              root / 'docs/evidence/rs2-12/rehearsal-03/rehearsal.json']
    if args.offline:
        files += [root / 'requirements-release-windows-py310.lock',
                  root / 'docs/evidence/rs2-12/offline-wheels.json',
                  root / 'docs/evidence/rs2-12/clean-install.json',
                  root / 'docs/evidence/rs2-12/rehearsal-signed-recovery/rehearsal.json',
                  root / 'docs/evidence/rs2-live-20261017/infrastructure-01/result.json',
                  root / 'docs/evidence/rs2-live-20261017/revocation.json',
                  root / 'docs/evidence/rs2-live-20261017/restored-state.json']
        files += sorted((root / '.rs2-release/dependency-wheels').glob('*.whl'))
    contents = {}
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Package member escaped allowlisted workspace')
        data = path.read_bytes()
        name = path.relative_to(root).as_posix()
        if name.startswith(('.rs2-release/wheels/', '.rs2-release/dependency-wheels/')):
            name = 'wheels/' + path.name
        elif re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/]{32}', data):
            raise ValueError('Possible private key material in ' + name)
        if name in contents: raise ValueError('Duplicate member')
        contents[name] = data
    if args.offline:
        pinned = json.loads((root / 'docs/evidence/rs2-12/offline-wheels.json').read_text())
        expected_wheels = {'wheels/' + item['file'] for item in pinned}
        if {name for name in contents if name.startswith('wheels/')} != expected_wheels:
            raise ValueError('Offline wheel set does not match tested manifest')
        for item in pinned:
            if hashlib.sha256(contents['wheels/' + item['file']]).hexdigest() != item['sha256']:
                raise ValueError('Offline wheel differs from tested bytes')
    manifest = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                for name, data in contents.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items(): archive.writestr(name, data)
        archive.writestr('MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip() is not None: raise ValueError('Archive CRC failed')
        saved = json.loads(archive.read('MANIFEST.json'))
        for name, item in saved.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != item['sha256']:
                raise ValueError('Archive digest mismatch')
    receipt = {'archive': args.output.name, 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
               'members': len(contents), 'manifest_verified': True,
               'scope': 'explicit allowlist and private-key-pattern checks, not a comprehensive secret audit'}
    args.output.with_suffix('.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
