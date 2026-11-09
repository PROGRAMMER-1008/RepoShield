"""Execute full and safe-selected tests for twelve authored mutations.

Development subprocess only; no arbitrary input repositories or isolation claims.
Each execution gets a fresh source copy to avoid pycache/coverage contamination.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.bench import MUTATIONS
from reposhield.demo import DATA
from reposhield.gitutil import DirTree, Change
from reposhield.graph import Graph
from reposhield.selector import select_tests
from reposhield.sandbox import SubprocessSandbox, Limits


def execute(root, paths):
    result = SubprocessSandbox().run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
         '--junitxml=result.xml', *paths], str(root), limits=Limits(timeout_seconds=60))
    xml = root / 'result.xml'
    cases = list(ET.parse(xml).iter('testcase')) if xml.exists() else []
    failures = [c.attrib for c in cases if c.find('failure') is not None or c.find('error') is not None]
    return {'process': result.to_dict(with_output=True), 'test_count': len(cases),
            'failures': failures, 'detected': result.exit_code == 1 and bool(failures),
            'valid_observation': result.exit_code in (0, 1) and bool(cases) and not result.timed_out}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    base = out / 'base'
    ignore = shutil.ignore_patterns('__pycache__', '.pytest_cache')
    shutil.copytree(DATA, base, ignore=ignore)
    graph = Graph.build(DirTree(str(base)))
    baseline = execute(base, graph.tests())
    (out / 'baseline.json').write_text(json.dumps(baseline, indent=2))
    if not baseline['valid_observation'] or baseline['process']['exit_code'] != 0:
        raise RuntimeError('Baseline suite must pass before mutation evaluation')
    rows = []
    for index, (name, path, old, new) in enumerate(MUTATIONS):
        source = out / f'mutation-{index:02d}'
        shutil.copytree(DATA, source, ignore=ignore)
        target = source / path; text = target.read_text()
        if old not in text: raise ValueError(f'Mutation anchor missing: {name}')
        target.write_text(text.replace(old, new, 1))
        start = time.perf_counter_ns()
        head = Graph.build(DirTree(str(source)))
        plan = select_tests(head, graph, [Change('M', path)], strategy='safe')
        selection_ns = time.perf_counter_ns() - start
        selected = [t.path for t in plan.tests]
        full_dir, selected_dir = out / f'full-{index:02d}', out / f'selected-{index:02d}'
        shutil.copytree(source, full_dir); shutil.copytree(source, selected_dir)
        full = execute(full_dir, graph.tests())
        subset = execute(selected_dir, selected) if selected else {'detected': False, 'valid_observation': False, 'reason': 'empty selection'}
        row = {'name': name, 'path': path, 'old': old, 'new': new, 'full_files': graph.tests(),
               'selected_files': selected, 'graph_and_selection_ns': selection_ns, 'full': full, 'selected': subset}
        rows.append(row)
        (out / 'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        print(f"{name}: full={full['detected']} selected={subset['detected']}", flush=True)
    return 0 if all(r['full']['detected'] and r['selected']['detected'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
