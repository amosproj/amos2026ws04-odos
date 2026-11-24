"""Cooperative stops, small scopes and additive review preservation. No paid calls."""
import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from odos import rule_extraction_jobs as rx
from odos.llm.document_extraction import extract_document, plan_chunks
from odos.llm.extraction_workflow import extract_rules_workflow
from odos.llm.incremental import eligible_chunks, merge_previous
from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.rule_extraction import ExtractionResult
from test_v2_document_input import document


def rule(identifier, element, value=3):
    return {'schemaVersion':'2.0','id':identifier,'source':{'documentId':'mbo','elements':[{'elementId':element,'role':'primary'}]},
        'classification':{'type':'obligation','summary':'Abstand mindestens 3 m.'},
        'requirements':[{'kind':'numeric','fact':'clearance','operator':'>=','value':value,'unit':'m'}],
        'review':{'status':'draft'}}


def entry(original, state='pending', edited=None):
    from odos.rule_reviews import canonical_sha256
    return {'ruleSha256':canonical_sha256(original),'state':state,'edited':edited is not None,
        'effectiveRule':edited,'at':datetime.now(timezone.utc).isoformat(),'reviewer':'Tester',
        'reason':'Checked','lastEventId':5,'verification':'unverified'}


class Model:
    config=BedrockConfig()
    def __init__(self, event=None, invalid=False): self.calls=0;self.event=event;self.invalid=invalid
    def converse(self, system,user,**kwargs):
        self.calls+=1
        if self.event:self.event.set()
        target='doc/par-6' if self.invalid else json.loads(user.split('\n',1)[1])['target']['structure'][0]['id']
        value={'id':'invalid'} if self.invalid else rule('generated',target)
        return BedrockResponse(json.dumps({'rules':[value]}),'end_turn',100,50,1,self.config.model_id)


class ControlTests(unittest.TestCase):
    def test_sample_validation_and_preview_plan_match(self):
        for size in (1,3,None):
            request=rx.RuleExtractionRequest(sampleChunks=size)
            with patch.object(rx,'load_bedrock_env'),patch.object(rx.BedrockConfig,'from_env',return_value=BedrockConfig()):
                preview=rx.preview_request(document(),request)
            context=rx.plan_request(document(),request)
            self.assertEqual(preview['chunks'],len(context['chunks']))
            self.assertEqual(preview['chunks'],2 if size is None else 1)
        for size in (0,2,4,True,'1'):
            with self.assertRaises(ValidationError):rx.RuleExtractionRequest(sampleChunks=size)

    def test_stop_before_start_makes_zero_model_calls(self):
        event=threading.Event();event.set();model=Model()
        result=extract_document(document(),client=model,should_stop=event.is_set)
        self.assertEqual(model.calls,0)
        self.assertTrue(result.report['partial'])
        self.assertEqual(len(result.report['integration']['stoppedChunks']),2)

    def test_stop_keeps_completed_chunk_and_does_not_submit_the_next(self):
        event=threading.Event();model=Model(event)
        result=extract_document(document(),client=model,max_workers=1,should_stop=event.is_set)
        self.assertEqual(model.calls,1);self.assertEqual(len(result.rules),1)
        self.assertEqual(result.report['integration']['stoppedChunks'],['doc/par-7'])
        self.assertTrue(result.generation['modelOutput']['partial'])

    def test_stop_prevents_schema_corrections(self):
        event=threading.Event();model=Model(event,invalid=True)
        result=extract_rules_workflow(document(),client=model,max_model_calls=3,should_stop=event.is_set)
        self.assertEqual(model.calls,1);self.assertTrue(result.report['stopped'])
        self.assertTrue(result.rules[0]['id'].endswith('invalid'))

    def test_all_accepted_or_edited_provisions_are_skipped_but_mixed_are_not(self):
        _,chunks=plan_chunks(document())
        first=rule('a','doc/par-6');second=rule('b','doc/par-7')
        reviews={'rules':{'a':entry(first,'accepted'),'b':entry(second,edited=second)}}
        remaining,skipped=eligible_chunks(chunks,{'rules':[first,second]},reviews)
        self.assertEqual(remaining,[]);self.assertEqual(len(skipped),2)
        pending=rule('c','doc/par-6')
        remaining,skipped=eligible_chunks(chunks,{'rules':[first,second,pending]},reviews)
        self.assertEqual([c.id for c in remaining],['doc/par-6'])

    def test_additive_merge_preserves_originals_edits_and_deduplicates(self):
        accepted=rule('a','doc/par-6');edited=rule('b','doc/par-7');manual=rule('b','doc/par-7',5)
        previous={'rules':[accepted,edited],'_generation':{'runId':'old'}};unchanged=copy.deepcopy(previous)
        state={'extractionId':'old-date','rules':{'a':entry(accepted,'accepted'),'b':entry(edited,edited=manual)}}
        duplicate=copy.deepcopy(accepted);duplicate['id']='fresh-id';duplicate['classification']['summary']='Rephrased.'
        new=rule('a','doc/par-7',8)
        result=ExtractionResult(rules=[duplicate,copy.deepcopy(manual),new],generation={'runId':'new-run'},report={})
        merge_previous(result,previous,state)
        self.assertEqual(previous,unchanged)
        self.assertEqual(result.rules[:2],[accepted,edited]);self.assertEqual(len(result.rules),3)
        self.assertNotEqual(result.rules[2]['id'],'a')
        self.assertEqual(result.generation['carriedReviews']['a']['state'],'accepted')
        self.assertEqual(result.generation['carriedReviews']['b']['effectiveRule'],manual)
        self.assertEqual(result.generation['carriedReviews']['b']['state'],'pending')
        self.assertNotIn(result.rules[2]['id'],result.generation['carriedReviews'])
        self.assertEqual(result.generation['incremental']['exactDuplicatesSkipped'],2)

    def test_carried_decisions_export_and_future_actions_use_new_extraction_identity(self):
        from odos import rule_reviews as rv
        from odos.artifact_names import RULE_JSON
        original=rule('a','doc/par-6');manual=rule('a','doc/par-6',5)
        carried=entry(original,'accepted',manual)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/RULE_JSON).write_text(json.dumps({'rules':[original],'_generation':{
                'generatedAt':'new-date','carriedReviews':{'a':carried}}}))
            with patch.object(rv.repo,'latest_events',return_value={}),patch.object(rv.repo,'earlier_event_count',return_value=1):
                state=rv.review_state('job',directory)
                self.assertEqual(state['extractionId'],'new-date')
                self.assertEqual(state['rules']['a']['lastEventId'],0)
                self.assertEqual(state['rules']['a']['state'],'accepted')
                exported=rv.approved_export('job',directory)
                self.assertEqual(exported['rules'][0]['requirements'][0]['value'],5)
                # Hash mismatch must never carry approval to changed model content.
                changed=rule('a','doc/par-6',9)
                (directory/RULE_JSON).write_text(json.dumps({'rules':[changed],'_generation':{
                    'generatedAt':'new-date','carriedReviews':{'a':carried}}}))
                self.assertEqual(rv.review_state('job',directory)['rules']['a']['state'],'pending')

    def test_sample_worker_saves_only_selected_chunks(self):
        from odos.artifact_names import LEGAL_JSON,RULE_JSON
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);(directory/LEGAL_JSON).write_text(json.dumps(document()))
            model=Model();request=rx.RuleExtractionRequest(sampleChunks=1)
            with patch.object(rx,'bedrock_client',return_value=model):
                state=rx.RuleExtraction.queued(request)
                result=rx.run(directory,request,state)
                self.assertFalse((directory/RULE_JSON).exists())
                rx.save_rules(result,directory)
            self.assertEqual(state.status,'completed');self.assertEqual(model.calls,1)
            self.assertTrue(state.modelOutput['partial'])
            self.assertEqual(len(json.loads((directory/RULE_JSON).read_text())['rules']),1)

    def test_incremental_worker_preserves_accepted_decision_end_to_end(self):
        from odos import rule_reviews as rv
        from odos.artifact_names import LEGAL_JSON,RULE_JSON
        first=rule('a','doc/par-6')
        old_event={'id':1,'decision':'accepted','edited_rule':None,'reviewer':'Tester','reason':'Checked',
            'created_at':datetime.now(timezone.utc),'rule_sha256':rv.canonical_sha256(first)}
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);(directory/LEGAL_JSON).write_text(json.dumps(document()))
            (directory/RULE_JSON).write_text(json.dumps({'rules':[first],'_generation':{'generatedAt':'old-date','runId':'old'}}))
            model=Model();request=rx.RuleExtractionRequest(sampleChunks=1)
            events=lambda doc_id,extraction_id: {'a':old_event} if extraction_id=='old-date' else {}
            with patch.object(rv.repo,'latest_events',side_effect=events),patch.object(rv.repo,'earlier_event_count',return_value=1),\
                 patch.object(rx,'bedrock_client',return_value=model):
                plan=rx.plan_request(document(),request,directory)
                self.assertEqual(plan['chunks'][0].selected_ids,['doc/par-7'])
                request._context=plan
                state=rx.RuleExtraction.queued(request)
                result=rx.run(directory,request,state)
                self.assertEqual(state.status,'completed');self.assertEqual(model.calls,1)
                rx.save_rules(result,directory)
                saved=json.loads((directory/RULE_JSON).read_text())
                self.assertEqual(saved['rules'][0],first)
                self.assertEqual(len(saved['rules']),2)
                state=rv.review_state(directory.name,directory)
                self.assertEqual(state['rules']['a']['state'],'accepted')
                self.assertEqual(state['rules'][saved['rules'][1]['id']]['state'],'pending')
                self.assertEqual(rv.approved_export(directory.name,directory)['rules'][0]['id'],'a')
                self.assertTrue(list((directory/'extraction-runs').glob('*/previous-rules.json')))

    def test_new_decision_after_carry_keeps_edit_and_uses_zero_event_baseline(self):
        from odos import rule_reviews as rv
        from odos.artifact_names import RULE_JSON
        original=rule('a','doc/par-6');manual=rule('a','doc/par-6',5)
        carried=entry(original,edited=manual)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);(directory/RULE_JSON).write_text(json.dumps({'rules':[original],'_generation':{
                'generatedAt':'new-date','carriedReviews':{'a':carried}}}))
            def append(*args):
                self.assertEqual(args[1],'new-date');self.assertEqual(args[4],0)
                self.assertEqual(args[-1],manual)
                return {'id':1,'decision':'accepted','edited_rule':args[-1],'reviewer':'Reviewer',
                    'reason':None,'created_at':datetime.now(timezone.utc)}
            with patch.object(rv.repo,'latest_events',return_value={}),patch.object(rv.repo,'append_event',side_effect=append,create=True):
                request=rv.ReviewRequest(ruleId='a',extractionId='new-date',expectedRuleSha256=rv.canonical_sha256(original),
                    expectedLastEventId=0,action='accept',reviewer='Reviewer')
                result=rv.record_review('job',directory,request)
                self.assertEqual(result['state'],'accepted');self.assertEqual(result['effectiveRule'],manual)

    def test_parallel_stop_waits_for_inflight_but_starts_no_later_chunks(self):
        stop=threading.Event();barrier=threading.Barrier(2);lock=threading.Lock()
        class Parallel(Model):
            def converse(self,system,user,**kwargs):
                with lock:self.calls+=1
                barrier.wait(timeout=3);stop.set()
                target=json.loads(user.split('\n',1)[1])['target']['structure'][0]['id']
                return BedrockResponse(json.dumps({'rules':[rule(target.replace('/','-'),target)]}),
                    'end_turn',100,50,1,self.config.model_id)
        legal=document()
        for n in (8,9):
            legal['structure'].append({'id':f'doc/par-{n}','type':'section','number':str(n),'text':'Abstand mindestens 3 m.'})
        model=Parallel()
        result=extract_document(legal,client=model,max_workers=2,should_stop=stop.is_set)
        self.assertEqual(model.calls,2);self.assertEqual(len(result.rules),2)
        self.assertEqual(len(result.report['integration']['stoppedChunks']),2)
