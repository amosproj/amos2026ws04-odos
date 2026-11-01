"""Reproduce research evidence using the existing uv environment; restores shapes."""
import contextlib
import copy
import hashlib
import importlib.metadata
import io
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import demo

BASE = demo.BASE
OUT = BASE / 'output/evidence'
OUT.mkdir(parents=True, exist_ok=True)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

run = subprocess.run([sys.executable, str(BASE/'demo.py'), 'test'], cwd=BASE,
                     capture_output=True, text=True, encoding='utf-8')
(OUT/'test-run.log').write_text(run.stdout + run.stderr, encoding='utf-8')
print(run.stdout, end='')
if run.returncode:
    print(run.stderr, file=sys.stderr)
    raise SystemExit(run.returncode)

rules = demo.load(BASE/'output/rules.json')
document = demo.load(BASE/'output/document.json')
tests = demo.load(BASE/'output/test_results.json')
assert document['page_count'] == 83
assert document['sha256'] == digest(BASE/'MusterBauVerordnung.pdf')
assert rules['source_document_sha256'] == document['sha256']
assert rules['source_clauses']['37.5']['pdf_page'] == 34
assert rules['source_clauses']['6.5']['pdf_page'] == 10
assert len(tests) == 17 and all(t['test_passed'] for t in tests)

# Compile a changed JSON threshold and save the actual generated shape as proof.
# Restore original bytes even on failure, including serializer/blank-node changes.
window = BASE/'output/window_shapes.ttl'
setback = BASE/'output/setback_shapes.ttl'
original_shapes = {p: p.read_bytes() for p in [window, setback]}
changed = copy.deepcopy(rules)
changed['escape_window']['properties'][0]['minInclusive'] = '1.00'
changed['escape_window']['properties'][0]['message'] = 'Mutation experiment: clear width must be at least 1.00 m.'
demo.save(OUT/'threshold-1m-rules.json', changed)
with contextlib.redirect_stdout(io.StringIO()) as log:
    try:
        baseline = demo.check(BASE/'samples/valid_boundary.ttl', window, 'evidence_baseline')
        demo.compile_rules(changed)
        shutil.copy2(window, OUT/'threshold-1m-shapes.ttl')
        mutated = demo.check(BASE/'samples/valid_boundary.ttl', window, 'evidence_threshold_1m')
    finally:
        for path, content in original_shapes.items(): path.write_bytes(content)
    restored = demo.check(BASE/'samples/valid_boundary.ttl', window, 'evidence_restored')
assert baseline['conforms'] and not mutated['conforms'] and restored['conforms']
demo.save(OUT/'threshold-experiment.json', {
    'input': 'samples/valid_boundary.ttl', 'input_width_m': '0.90',
    'baseline_threshold_m': '0.90', 'modified_threshold_m': '1.00',
    'baseline': baseline, 'modified': mutated, 'restored': restored,
    'original_shapes_restored_byte_for_byte': all(p.read_bytes()==b for p,b in original_shapes.items())})

files = ['demo.py','collect_evidence.py','pyproject.toml','uv.lock','uv.toml',
         'rules/template.json','MusterBauVerordnung.pdf', 'output/document.json',
         'output/rules.json','output/window_shapes.ttl','output/setback_shapes.ttl',
         'output/test_results.json']
files += [str(p.relative_to(BASE)) for p in sorted((BASE/'samples').glob('*.ttl'))]
environment = {
    'collected_at': datetime.now(timezone.utc).isoformat(),
    'python': platform.python_version(),
    'operating_system': platform.system(), 'architecture': platform.machine(),
    'packages': {p: importlib.metadata.version(p) for p in ['pyshacl','rdflib','pypdfium2']},
    'uv': subprocess.check_output([shutil.which('uv') or 'uv', '--version'], text=True, encoding='utf-8').strip(),
    'page_count': document['page_count'], 'segmented_section_count': len(document['sections']),
    'tests_total': len(tests), 'tests_passed': sum(t['test_passed'] for t in tests),
    'source_document_sha256': document['sha256'],
    'artifact_sha256': {f: digest(BASE/f) for f in files}}
demo.save(OUT/'environment.json', environment)
print('Verified source provenance, 17 expected outcomes, and JSON threshold mutation; original shapes restored.')

