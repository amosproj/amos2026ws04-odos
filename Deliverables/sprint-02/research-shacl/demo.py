"""MBO PDF -> extracted JSON -> manually interpreted rule JSON -> SHACL -> reports.
Use uv run demo.py --help. No automatic legal interpretation or LLM is used.
"""
import argparse
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
import pypdfium2 as pdfium
from pyshacl import validate
from rdflib import Graph, Namespace, RDF, XSD, BNode, Literal
from rdflib.collection import Collection

BASE = Path(__file__).resolve().parent
EX = Namespace('https://example.org/amos/mbo#')
SH = Namespace('http://www.w3.org/ns/shacl#')

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def graph():
    g = Graph()
    for prefix, ns in [('ex', EX), ('sh', SH), ('xsd', XSD)]: g.bind(prefix, ns)
    return g

def extract(pdf):
    pages = []
    with pdfium.PdfDocument(str(pdf)) as doc:
        for i in range(len(doc)):
            page = doc[i]
            tp = page.get_textpage()
            text = tp.get_text_range().replace('\r\n','\n').replace('\r','\n')
            text = re.sub(r'\n{3,}', '\n\n', text)
            pages.append({'pdf_page': i+1, 'text': text})
            tp.close()
            page.close()
    chunks = [re.sub(r'^\s*\d+\s*\n', '', p['text']) for p in pages]
    # PDF text omits the section sign before 23; repair only the exact known heading.
    chunks = [re.sub(r'(?m)^23\n(?=Zertifizierung\n)', '§ 23\n', c) for c in chunks]
    joined = '\n'.join(chunks)
    offsets, cursor = [], 0
    for chunk in chunks:
        offsets.append(cursor)
        cursor += len(chunk)+1
    heads = list(re.finditer(r'(?m)^§\s*(\d+[a-z]?)\s*\n', joined))
    sections = []
    for i, h in enumerate(heads):
        end = heads[i+1].start() if i+1 < len(heads) else len(joined)
        raw = joined[h.end():end]
        block_start = h.end() + len(raw) - len(raw.lstrip())
        block = raw.strip()
        matches = list(re.finditer(r'(?m)^\((\d+)\)\s*', block))
        subs = []
        for j, m in enumerate(matches):
            stop = matches[j+1].start() if j+1 < len(matches) else len(block)
            subs.append({'number': int(m.group(1)), 'pdf_page': sum(o <= block_start + m.start() for o in offsets), 'text': re.sub(r'\s+', ' ', block[m.end():stop]).strip()})
        title = block[:matches[0].start()] if matches else block.split('\n')[0]
        sections.append({'number': h.group(1), 'title': re.sub(r'\s+', ' ', title).strip(),
                         'pdf_page_start': sum(o <= h.start() for o in offsets), 'text': block, 'subsections': subs})
    data = {'document_id': 'MBO-local-2024', 'source_file': pdf.name,
            'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(), 'page_count': len(pages),
            'known_segmentation_repairs': ['PDF page 19: missing section sign before 23 / Zertifizierung restored for segmentation only; raw pages unchanged.'],
            'extraction_note': 'All page text retained. Section/subsection parsing is heuristic, not a complete legal-document parser.',
            'pages': pages, 'sections': sections}
    save(BASE/'output/document.json', data)
    print(f'Extracted {len(pages)} pages, {len(sections)} section headings -> output/document.json')
    return data

def prepare_rules(document):
    rules = load(BASE/'rules/template.json')
    clauses = {}
    for sec, sub, phrases in [('37', 5, ['0,90 m x 1,20 m','Fußbodenoberkante','Traufkante']),
                              ('6', 5, ['0,4 H','mindestens 3 m'])]:
        s = next(s for s in document['sections'] if s['number'] == sec)
        paragraph = next(p for p in s['subsections'] if p['number'] == sub)
        text = paragraph['text']
        for phrase in phrases:
            if phrase not in text: raise ValueError(f'Source differs from interpreted template: {sec}({sub}): {phrase}')
        clauses[f'{sec}.{sub}'] = {'section': sec, 'subsection': sub, 'pdf_page': paragraph['pdf_page'], 'text': text}
    rules['source_document_sha256'] = document['sha256']
    rules['source_clauses'] = clauses
    save(BASE/'output/rules.json', rules)
    print('Attached source clauses to MANUALLY interpreted rules -> output/rules.json')
    return rules

def prop(g, parent, spec):
    p = BNode()
    g.add((parent, SH.property, p))
    g.add((p, SH.path, EX[spec['property']]))
    g.add((p, SH.minCount, Literal(1)))
    g.add((p, SH.maxCount, Literal(1)))
    g.add((p, SH.message, Literal(spec.get('message', spec['property']))))
    if 'equals' in spec: g.add((p, SH.hasValue, Literal(spec['equals'])))
    else: g.add((p, SH.datatype, XSD[spec.get('datatype', 'decimal')]))
    for key in ['minInclusive','maxInclusive']:
        if key in spec: g.add((p, SH[key], Literal(Decimal(str(spec[key])), datatype=XSD.decimal)))

def compile_rules(rules):
    g = graph()
    w = rules['escape_window']
    s = EX.EscapeWindowShape
    g.add((s, RDF.type, SH.NodeShape))
    g.add((s, SH.targetClass, EX[w['targetClass']]))
    g.add((s, SH.description, Literal('MBO section 37(5); see rules.json for source and interpretation assumptions.')))
    for spec in w['properties']: prop(g, s, spec)
    head = BNode()
    Collection(g, head, [EX.NonRoofBranch, EX.RoofBranch])
    g.add((s, SH['or'], head))
    prop(g, EX.NonRoofBranch, {'property':'inRoofSlopeOrRoofStructure','equals':False})
    prop(g, EX.RoofBranch, {'property':'inRoofSlopeOrRoofStructure','equals':True})
    options = []
    for spec in w['roof_distance_alternatives']:
        n = BNode()
        prop(g, n, spec)
        options.append(n)
    head = BNode()
    Collection(g, head, options)
    g.add((EX.RoofBranch, SH['or'], head))
    g.serialize(BASE/'output/window_shapes.ttl', format='turtle')
    g = graph()
    a = rules['general_setback']
    s = EX.GeneralSetbackShape
    g.add((s, RDF.type, SH.NodeShape))
    g.add((s, SH.targetClass, EX[a['targetClass']]))
    g.add((s, SH.description, Literal('Section 6(5) sentence 1 ONLY; H derivation and exceptions excluded.')))
    for spec in a['properties']: prop(g, s, spec)
    factor, minimum = Decimal(a['factor']), Decimal(a['minimumM'])
    if factor < 0 or minimum < 0: raise ValueError('Negative rule parameter')
    c = BNode()
    g.add((s, SH.sparql, c))
    g.add((c, SH.message, Literal('Setback depth must be at least max(factor * H, minimumM).')))
    query = f'''PREFIX ex: <{EX}>
SELECT $this ?value WHERE {{
 $this ex:effectiveHeightHM ?h ; ex:setbackDepthM ?value .
 BIND(({factor} * ?h) AS ?scaled)
 BIND(IF(?scaled > {minimum}, ?scaled, {minimum}) AS ?required)
 FILTER(?value < ?required)
}}'''
    g.add((c, SH.select, Literal(query)))
    g.serialize(BASE/'output/setback_shapes.ttl', format='turtle')
    print('Compiled rule JSON -> output/window_shapes.ttl and setback_shapes.ttl')

def check(data_file, shapes_file, name):
    data = Graph().parse(data_file, format='turtle')
    shapes = Graph().parse(shapes_file, format='turtle')
    targets = {n for cls in shapes.objects(None, SH.targetClass) for n in data.subjects(RDF.type, cls)}
    if not targets: raise ValueError('No explicitly typed target objects; refusing a vacuous pass. Check classes and namespaces.')
    conforms, report, text = validate(data, shacl_graph=shapes, inference='none', meta_shacl=True)
    if not isinstance(report, Graph): raise RuntimeError(str(report))
    out = BASE/'output/reports'
    out.mkdir(parents=True, exist_ok=True)
    report.serialize(out/f'{name}.ttl', format='turtle')
    (out/f'{name}.txt').write_text(text, encoding='utf-8')
    results = []
    for r in report.subjects(RDF.type, SH.ValidationResult):
        results.append({k: str(value) if (value := report.value(r,p)) is not None else '' for k,p in [('focus_node',SH.focusNode),('path',SH.resultPath),('value',SH.value),('message',SH.resultMessage),('constraint',SH.sourceConstraintComponent)]})
    result = {'conforms':bool(conforms), 'target_count':len(targets), 'results':results}
    save(out/f'{name}.json', result)
    return result

def samples():
    directory = BASE/'samples'
    directory.mkdir(exist_ok=True)
    tests = []
    def window(name, expected, **changes):
        values = {'clearWidthM':'0.90','clearHeightM':'1.20','heightAboveFloorM':'1.20','inRoofSlopeOrRoofStructure':False}
        values.update(changes)
        g = graph()
        g.add((EX[name], RDF.type, EX.EscapeWindow))
        for key,value in values.items():
            if value is None: continue
            literal = Literal(value) if isinstance(value,bool) else Literal(Decimal(value),datatype=XSD.decimal)
            g.add((EX[name], EX[key], literal))
        if name == 'wrong_datatype': g.set((EX[name],EX.clearWidthM,Literal('0.90')))
        if name == 'wrong_boolean': g.set((EX[name],EX.inRoofSlopeOrRoofStructure,Literal('false')))
        g.serialize(directory/f'{name}.ttl',format='turtle')
        tests.append({'file':f'{name}.ttl','shapes':'window_shapes.ttl','expected':expected})
    window('valid_boundary', True)
    window('too_narrow', False, clearWidthM='0.89')
    window('too_short', False, clearHeightM='1.19')
    window('too_high', False, heightAboveFloorM='1.21')
    window('missing_width', False, clearWidthM=None)
    window('wrong_datatype', False)
    window('wrong_boolean', False)
    window('roof_edge_boundary', True, inRoofSlopeOrRoofStructure=True, lowerEdgeHorizontalDistanceToEavesM='1.00')
    window('roof_too_far', False, inRoofSlopeOrRoofStructure=True, lowerEdgeHorizontalDistanceToEavesM='1.01')
    window('roof_missing_distance', False, inRoofSlopeOrRoofStructure=True)
    window('roof_step_alternative', True, inRoofSlopeOrRoofStructure=True, lowerEdgeHorizontalDistanceToEavesM='1.50', stepHorizontalDistanceToEavesM='0.80')
    window('missing_roof_classification', False, inRoofSlopeOrRoofStructure=None)
    for name,h,depth,expected in [('setback_boundary','10','4',True),('setback_too_small','10','3.99',False),('setback_minimum','5','3',True),('setback_below_minimum','5','2.99',False)]:
        g = graph()
        g.add((EX[name],RDF.type,EX.GeneralSetbackCase))
        g.add((EX[name],EX.effectiveHeightHM,Literal(Decimal(h),datatype=XSD.decimal)))
        g.add((EX[name],EX.setbackDepthM,Literal(Decimal(depth),datatype=XSD.decimal)))
        g.serialize(directory/f'{name}.ttl',format='turtle')
        tests.append({'file':f'{name}.ttl','shapes':'setback_shapes.ttl','expected':expected})
    g = graph()
    g.add((EX.UnclassifiedWindow,RDF.type,EX.Window))
    g.serialize(directory/'no_target.ttl',format='turtle')
    save(directory/'manifest.json',tests)
    print(f'Created {len(tests)+1} editable RDF examples -> samples/')

def suite():
    outcomes = []
    for case in load(BASE/'samples/manifest.json'):
        result = check(BASE/'samples'/case['file'],BASE/'output'/case['shapes'],Path(case['file']).stem)
        ok = result['conforms'] == case['expected']
        print(f"{'OK' if ok else 'FAIL'} {case['file']}: conforms={result['conforms']} expected={case['expected']}")
        outcomes.append({**case,'actual':result['conforms'],'test_passed':ok})
    try: check(BASE/'samples/no_target.ttl',BASE/'output/window_shapes.ttl','no_target')
    except ValueError as error: ok = str(error).startswith('No explicitly typed target objects;')
    else: ok = False
    outcomes.append({'file':'no_target.ttl','test_passed':ok,'expected':'reject no target'})
    print(f"{'OK' if ok else 'FAIL'} no_target.ttl: must reject instead of silently passing")
    save(BASE/'output/test_results.json',outcomes)
    passed = sum(x['test_passed'] for x in outcomes)
    print(f'{passed}/{len(outcomes)} tests passed. Reports: output/reports/')
    return 0 if passed == len(outcomes) else 1

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',nargs='?',default='all',choices=['all','extract','compile','test','validate'])
    p.add_argument('--pdf',type=Path,default=BASE/'MusterBauVerordnung.pdf')
    p.add_argument('--rules',type=Path,default=BASE/'output/rules.json')
    p.add_argument('--data',type=Path)
    p.add_argument('--shapes',type=Path,default=BASE/'output/window_shapes.ttl')
    a = p.parse_args()
    (BASE/'output').mkdir(exist_ok=True)
    if a.command in ['all','extract']:
        doc = extract(a.pdf)
        if a.command == 'all':
            compile_rules(prepare_rules(doc))
            samples()
            return suite()
    elif a.command == 'compile': compile_rules(load(a.rules))
    elif a.command == 'test': return suite()
    elif a.command == 'validate':
        if not a.data: p.error('validate requires --data PATH')
        result = check(a.data,a.shapes,'custom')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['conforms'] else 1
    return 0

if __name__ == '__main__': raise SystemExit(main())



