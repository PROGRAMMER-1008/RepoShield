"""Consolidate verified candidate archives without copying trusted runtime files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def verified_members(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read('MANIFEST.json'))
        if len(names) != len(set(names)) or set(names) != set(manifest) | {'MANIFEST.json'}:
            raise ValueError('Archive member set mismatch')
        contents = {}
        for name, expected in manifest.items():
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:
                raise ValueError('Unsafe archive member')
            data = archive.read(name)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError('Archive integrity failure')
            contents[name] = data
        return contents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    archives = ['reposhield-offline-windows-py310-20261017-v4-ui.zip',
                'reposhield-acceptance-supplement-20261018.zip',
                'reposhield-recovery-supplement-20261020.zip']
    contents = {}
    provenance = []
    for name in archives:
        path = root / '.rs2-release' / name
        contents.update(verified_members(path))
        provenance.append({'archive': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    # Explicit current-document/evidence allowlist; never traverse trusted runtime.
    for name in ('docs/IMPLEMENTATION_STATUS.md', 'docs/FINAL_ACCEPTANCE_CHECKLIST.md',
                 'docs/OPERATOR_HANDOFF.md', 'docs/SUBMISSION_START_HERE.md',
                 'docs/evidence/final-20261101/tests.xml', 'benchmark/assemble_submission.py'):
        contents[name] = (root / name).read_bytes()
    contents['CANDIDATE_PROVENANCE.json'] = json.dumps(provenance, indent=2).encode()
    manifest = {n: {'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest()} for n, d in contents.items()}
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items(): archive.writestr(name, data)
        archive.writestr('MANIFEST.json', json.dumps(manifest, indent=2))
    assert verified_members(args.output) == contents
    receipt = {'archive': args.output.name, 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
               'members': len(contents), 'manifest_verified': True, 'final_release': False}
    args.output.with_suffix('.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == '__main__': main()
