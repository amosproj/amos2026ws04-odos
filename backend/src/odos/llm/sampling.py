"""Random, reproducible groups of at most four actual articles/§ provisions."""
import hashlib
import random
from fastapi import HTTPException
from odos.llm.document_extraction import Chunk, _target_scope
from odos.llm.rule_extraction import _walk, scope_document
from odos.llm.incremental import eligible_chunks


def provision_candidates(scoped):
    nodes=list(_walk(scoped['structure']))
    articles=[node for node in nodes if node.get('type')=='article']
    provisions=articles or [node for node in nodes if node.get('type')=='section' and
                            (node.get('number') is not None or '/par-' in node['id'])]
    return [Chunk(n['id'],'provision',_target_scope(scoped,n),
                  [{k:n[k] for k in ('id','type','number','title') if k in n}]) for n in provisions]


def selected_groups(scoped, previous, reviews, selected_ids):
    candidates=provision_candidates(scoped)
    eligible,_=eligible_chunks(candidates,previous,reviews)
    allowed={c.id for c in eligible}
    labels=[]
    for c in candidates:
        root=c.path[-1]
        labels.append({'id':c.id,'type':root['type'],'number':str(root.get('number','')),
                       'title':root.get('title') or '', 'eligible':c.id in allowed})
    if not selected_ids:
        return [],[c.id for c in candidates if c.id not in allowed],len(eligible),[],labels
    groups,skipped,total,chosen=sample_groups(scoped,previous,reviews,
                                            max(1,(len(selected_ids)+3)//4),selected_ids=selected_ids)
    for index,group in enumerate(groups):
        group.kind='selected_provisions'
        group.path[0]['title']=f'Selected provisions, group {index+1}'
    return groups,skipped,total,chosen,labels


def sample_groups(scoped, previous, reviews, count, seed=None, selected_ids=None):
    nodes=list(_walk(scoped['structure']))
    articles=[node for node in nodes if node.get('type')=='article']
    kind='article' if articles else 'section'
    provisions=articles or [node for node in nodes if node.get('type')=='section' and
                            (node.get('number') is not None or '/par-' in node['id'])]
    candidates=[Chunk(n['id'],'provision',_target_scope(scoped,n),
                      [{k:n[k] for k in ('id','type','number','title') if k in n}]) for n in provisions]
    eligible,skipped=eligible_chunks(candidates,previous,reviews)
    by_id={c.id:c for c in eligible}
    if selected_ids is not None:
        if len(set(selected_ids))!=len(selected_ids) or len(selected_ids)>count*4:
            raise HTTPException(422,'A sample must contain unique provision IDs, at most four per group.')
        if any(identifier not in by_id for identifier in selected_ids):
            raise HTTPException(409,'The preview selection is no longer eligible. Reopen the preview before starting.')
        chosen=set(selected_ids)
    else:
        generator=random.Random(seed) if seed is not None else random.SystemRandom()
        chosen=set(generator.sample(list(by_id),min(count*4,len(by_id))))
    ordered=[c for c in eligible if c.id in chosen]
    groups=[];labels=[]
    for offset in range(0,len(ordered),4):
        batch=ordered[offset:offset+4]
        ids=[c.id for c in batch]
        target=scope_document(scoped,ids)
        # Only descendants of selected provisions own legal text; ancestor labels
        # remain for structure, while ancestor prose/sentences are excluded.
        owned=set()
        for node in nodes:
            if node['id'] in chosen and node['id'] in ids:
                owned.update(n['id'] for n in _walk([node]))
        for node in _walk(target['structure']):
            if node['id'] not in owned:node.pop('text',None)
        target['sentences']=[s for s in target.get('sentences',[]) if all(r['elementId'] in owned for r in s.get('ranges',[]))]
        target['footnotes']=[f for f in target.get('footnotes',[]) if any(a in owned for a in f.get('anchorElementIds',[]))]
        identifier='sample-'+hashlib.sha256('\n'.join(ids).encode()).hexdigest()[:16]
        groups.append(Chunk(identifier,'random_sample',target,
                            [{'id':identifier,'type':'sample','title':f'Random sample {len(groups)+1}'}],ids))
        for c in batch:
            root=next(n for n in nodes if n['id']==c.id)
            labels.append({'id':c.id,'type':kind,'number':str(root.get('number','')),
                           'title':root.get('title') or '', 'group':len(groups)})
    return groups,skipped,len(eligible),labels
