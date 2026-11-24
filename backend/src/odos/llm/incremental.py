"""Lossless additive extraction revisions. Human decisions remain bound to exact originals."""
from __future__ import annotations
import copy
import hashlib
import json


def fingerprint(rule):
    value = copy.deepcopy(rule)
    value.pop('id', None); value.pop('review', None)
    if isinstance(value.get('classification'), dict):
        value['classification'].pop('summary', None)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def source_ids(rule):
    source = rule.get('source', {})
    elements = source.get('elements', []) if isinstance(source, dict) else []
    return {e['elementId'] for e in elements if isinstance(e, dict) and isinstance(e.get('elementId'), str)
            and e.get('role', 'primary') == 'primary'} if isinstance(elements, list) else set()


def eligible_chunks(chunks, previous, reviews):
    """Skip a provision only when it has rules and all of its existing rules are protected.

    This is a cost-saving restart policy, not proof of completeness. Mixed provisions
    may be processed again; their protected records are never replaced.
    """
    from odos.llm.rule_extraction import _walk
    out, skipped = [], []
    protected = {key for key, e in reviews.get('rules', {}).items() if e['state'] == 'accepted' or e['edited']}
    for chunk in chunks:
        owned = {n['id'] for n in _walk(chunk.target['structure'])}
        prior = [rule for rule in previous.get('rules', []) if source_ids(rule) & owned]
        if prior and all(rule.get('id') in protected for rule in prior):
            skipped.append(chunk.id)
        else:
            out.append(chunk)
    return out, skipped


def merge_previous(result, previous, reviews):
    """Keep every prior original and its review overlay; append only novel draft candidates.

    A new generatedAt/runId identifies this revision. Carried review state is stored
    with hashes and origin IDs, rather than accepting fresh model output automatically.
    """
    original = copy.deepcopy(previous.get('rules', []))
    entries = reviews.get('rules', {})
    seen = {fingerprint(rule) for rule in original}
    seen.update(fingerprint(e['effectiveRule']) for e in entries.values() if e.get('effectiveRule'))
    used = {rule.get('id') for rule in original}
    added, duplicates = [], 0
    for candidate in result.rules:
        key = fingerprint(candidate)
        if key in seen:
            duplicates += 1
            continue
        value = copy.deepcopy(candidate)
        base = str(value.get('id', 'rule'))[:220]
        if base in used:
            base += '-revision-' + str(result.generation['runId'])[:8]
        suffix = 1
        identifier = base
        while identifier in used:
            suffix += 1; identifier = f'{base}-{suffix}'
        value['id'] = identifier
        used.add(identifier); seen.add(key); added.append(value)
    carry = {}
    for rule in original:
        entry = entries.get(rule.get('id'))
        digest = hashlib.sha256(json.dumps(rule, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if entry and entry.get('ruleSha256') == digest and (entry['state'] != 'pending' or entry['edited']):
            carry[rule['id']] = {**copy.deepcopy(entry), 'fromExtractionId': reviews['extractionId'], 'lastEventId': 0}
    result.rules = original + added
    result.generation['carriedReviews'] = carry
    result.generation['incremental'] = {'parentExtractionId': reviews.get('extractionId'),
        'parentRunId': previous.get('_generation', {}).get('runId'),
        'previousRulesRetained': len(original), 'newCandidates': len(added), 'exactDuplicatesSkipped': duplicates,
        'protectedRules': sum(e['state'] == 'accepted' or e['edited'] for e in entries.values()),
        'policy': 'additive; previous originals and manual edits retained; novel candidates require review'}
    result.report['incremental'] = result.generation['incremental']
    result.report['carriedReviews'] = carry
    # Inspect effective content for truthful combined counts/coverage; never rewrite
    # an original record, because its existing decision applies to its exact hash.
    return result
