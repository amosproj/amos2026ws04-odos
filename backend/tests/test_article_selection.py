"""Explicit checklist scope, empty discovery, and whole-document processing."""
import unittest
import json
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError
from odos import rule_extraction_jobs as rx
from odos.llm.bedrock import BedrockConfig
from odos.llm.document_extraction import prepare_chunk
from odos.llm.rule_extraction import _walk
from odos.llm.sampling import selected_groups
from odos.llm_input.artifacts import build_inputs
from test_random_article_samples import eu
from test_extraction_controls import rule,entry
from test_v2_document_input import document as mbo


class ArticleSelectionTests(unittest.TestCase):
    def preview(self,request,legal=None):
        with patch.object(rx,'load_bedrock_env'),patch.object(rx.BedrockConfig,'from_env',return_value=BedrockConfig()):
            return rx.preview_request(legal or eu(),request)

    def test_empty_checklist_lists_provisions_without_requests(self):
        result=self.preview(rx.RuleExtractionRequest(articleIds=[]))
        self.assertFalse(result['canStart']);self.assertEqual(result['maximumModelCalls'],0)
        self.assertEqual(result['estimatedInitialInputTokens'],0)
        self.assertEqual(len(result['availableArticles']),19)
        self.assertNotIn('doc/art-12',[a['id'] for a in result['availableArticles']])
        self.assertTrue(all(a['title'] and a['eligible'] for a in result['availableArticles']))

    def test_selected_ids_only_are_sent_and_preview_matches_start(self):
        ids=['doc/art-3','doc/art-8','doc/art-18']
        request=rx.RuleExtractionRequest(articleIds=ids)
        preview=self.preview(request)
        self.assertEqual(preview['articleIds'],ids)
        self.assertEqual(preview['selectedArticleIds'],ids)
        self.assertEqual(preview['chunks'],1)
        plan=rx.plan_request(eu(),rx.RuleExtractionRequest(articleIds=ids))
        prepared,_=prepare_chunk(eu(),plan['chunks'][0],BedrockConfig())
        payload=json.loads(prepared.user.split('\n',1)[1])
        actual=[n['id'] for n in _walk(payload['target']['structure']) if n['type']=='article']
        self.assertEqual(actual,ids)
        self.assertNotIn('UNSELECTED ANCESTOR PROSE',prepared.user)

    def test_more_than_twelve_articles_allowed_and_grouped_by_four(self):
        ids=[f'doc/art-{n}' for n in range(1,20) if n!=12]
        result=self.preview(rx.RuleExtractionRequest(articleIds=ids))
        self.assertEqual(len(result['selectedArticleIds']),18)
        self.assertEqual(result['chunks'],5)
        self.assertEqual(result['maximumModelCalls'],5)

    def test_whole_document_keeps_normal_chunks_including_annex(self):
        legal=eu();legal['structure'].append({'id':'annex','type':'annex','text':'Technical annex.'})
        whole=rx.plan_request(legal,rx.RuleExtractionRequest(articleIds=None))
        selected=rx.plan_request(legal,rx.RuleExtractionRequest(articleIds=['doc/art-3']))
        self.assertTrue(any(c.id=='annex' for c in whole['chunks']))
        self.assertEqual(selected['chunks'][0].selected_ids,['doc/art-3'])
        self.assertNotIn('annex',{n['id'] for n in _walk(selected['chunks'][0].target['structure'])})

    def test_protected_entries_are_listed_disabled_and_cannot_be_selected(self):
        scoped=build_inputs(eu())[1];original=rule('accepted','doc/art-3')
        previous={'rules':[original]};reviews={'rules':{'accepted':entry(original,'accepted')}}
        groups,skipped,total,chosen,available=selected_groups(scoped,previous,reviews,[])
        self.assertFalse(next(a for a in available if a['id']=='doc/art-3')['eligible'])
        with self.assertRaises(HTTPException) as failure:
            selected_groups(scoped,previous,reviews,['doc/art-3'])
        self.assertEqual(failure.exception.status_code,409)

    def test_mbo_checklist_uses_sections(self):
        preview=self.preview(rx.RuleExtractionRequest(articleIds=[]),mbo())
        self.assertEqual([a['id'] for a in preview['availableArticles']],['doc/par-6','doc/par-7'])
        self.assertEqual(preview['availableArticles'][0]['type'],'section')

    def test_duplicates_unknown_excluded_or_conflicting_scope_are_rejected(self):
        for ids in [['doc/art-3','doc/art-3'],['doc/art-12'],['unknown']]:
            with self.assertRaises(HTTPException):rx.plan_request(eu(),rx.RuleExtractionRequest(articleIds=ids))
        with self.assertRaises(HTTPException):rx.plan_request(eu(),rx.RuleExtractionRequest(articleIds=['doc/art-3'],sampleChunks=1))
        with self.assertRaises(ValidationError):rx.RuleExtractionRequest(articleIds=['x']*101)

    def test_checklist_discovery_and_preview_do_not_mutate_source(self):
        import copy
        legal=eu();before=copy.deepcopy(legal)
        self.preview(rx.RuleExtractionRequest(articleIds=[]),legal)
        self.preview(rx.RuleExtractionRequest(articleIds=['doc/art-3']),legal)
        self.assertEqual(legal,before)

    def test_worker_generates_only_checked_articles_and_records_selection(self):
        import tempfile
        from pathlib import Path
        from odos.artifact_names import LEGAL_JSON,RULE_JSON
        from odos.llm.bedrock import BedrockResponse
        class Model:
            config=BedrockConfig()
            def __init__(self):self.payloads=[]
            def converse(self,system,user,**kwargs):
                payload=json.loads(user.split('\n',1)[1]);self.payloads.append(payload)
                identifier=next(n['id'] for n in _walk(payload['target']['structure']) if n['type']=='article')
                return BedrockResponse(json.dumps({'rules':[rule('new',identifier)]}),'end_turn',100,50,1,self.config.model_id)
        ids=['doc/art-3','doc/art-8']
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);(directory/LEGAL_JSON).write_text(json.dumps(eu()))
            request=rx.RuleExtractionRequest(articleIds=ids);request._context=rx.plan_request(eu(),request,directory)
            model=Model()
            with patch.object(rx,'bedrock_client',return_value=model):
                finished=rx.run(directory,request,rx.RuleExtraction.queued(request))
            self.assertEqual(finished.status,'completed');self.assertEqual(len(model.payloads),1)
            actual=[n['id'] for n in _walk(model.payloads[0]['target']['structure']) if n['type']=='article']
            self.assertEqual(actual,ids)
            saved=json.loads((directory/RULE_JSON).read_text())
            self.assertEqual(saved['_generation']['selection']['articleIds'],ids)
            self.assertTrue(saved['_generation']['modelOutput']['partial'])
