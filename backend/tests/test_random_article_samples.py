"""Four real random provisions per request, stable from preview to start."""
import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from odos import rule_extraction_jobs as rx
from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.document_extraction import prepare_chunk, extract_document
from odos.llm.rule_extraction import _walk
from test_extraction_controls import document as mbo, rule, entry


def eu():
    return {'id':'verordnung-2023-1230','title':'Machinery regulation','documentType':'eu_regulation','language':'en',
        'structure':[{'id':'doc/chapter','type':'chapter','number':'1','text':'UNSELECTED ANCESTOR PROSE',
                      'children':[{'id':f'doc/art-{n}','type':'article','number':str(n),'title':f'Title {n}',
                                   'text':f'Article {n}: clearance at least 3 m.'} for n in range(1,21)]}],
        'sentences':[],'footnotes':[]}


class RandomSampleTests(unittest.TestCase):
    def preview(self, request, legal=None):
        with patch.object(rx,'load_bedrock_env'),patch.object(rx.BedrockConfig,'from_env',return_value=BedrockConfig()):
            return rx.preview_request(legal or eu(),request)

    def test_one_sample_is_four_unique_actual_articles_not_chapters(self):
        request=rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=3)
        context=rx.plan_request(eu(),request)
        self.assertEqual(len(context['chunks']),1)
        chunk=context['chunks'][0]
        self.assertEqual(len(chunk.selected_ids),4);self.assertEqual(len(set(chunk.selected_ids)),4)
        self.assertTrue(all(identifier.startswith('doc/art-') for identifier in chunk.selected_ids))
        self.assertNotIn('doc/art-12',chunk.selected_ids)  # V2 policy
        prepared,_=prepare_chunk(eu(),chunk,BedrockConfig())
        body=json.loads(prepared.user.split('\n',1)[1])
        articles=[n['id'] for n in _walk(body['target']['structure']) if n['type']=='article']
        self.assertEqual(articles,chunk.selected_ids)
        self.assertNotIn('UNSELECTED ANCESTOR PROSE',prepared.user)
        self.assertEqual(prepared.scope,chunk.selected_ids)

    def test_preview_start_uses_exact_displayed_ids_even_with_different_seed(self):
        preview=self.preview(rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=3))
        start=rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=999,sampleArticleIds=preview['selectedArticleIds'])
        context=rx.plan_request(eu(),start)
        self.assertEqual(context['chunks'][0].selected_ids,preview['selectedArticleIds'])
        self.assertEqual(len(preview['sampleArticles']),4)
        self.assertEqual(preview['maximumModelCalls'],1)
        self.assertTrue(all(a['title'] for a in preview['sampleArticles']))

    def test_same_seed_stable_and_other_seed_can_choose_other_articles(self):
        a=self.preview(rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=3))
        b=self.preview(rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=3,maxModelCalls=3))
        c=self.preview(rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=4))
        self.assertEqual(a['selectedArticleIds'],b['selectedArticleIds'])
        self.assertNotEqual(a['selectedArticleIds'],c['selectedArticleIds'])

    def test_three_samples_are_twelve_articles_with_no_repetition(self):
        context=rx.plan_request(eu(),rx.RuleExtractionRequest(sampleChunks=3,sampleSeed=3))
        ids=[identifier for chunk in context['chunks'] for identifier in chunk.selected_ids]
        self.assertEqual(len(context['chunks']),3);self.assertEqual(len(ids),12);self.assertEqual(len(set(ids)),12)
        self.assertTrue(all(len(chunk.selected_ids)==4 for chunk in context['chunks']))

    def test_fewer_than_four_uses_only_available_mbo_sections(self):
        context=rx.plan_request(mbo(),rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=3))
        self.assertEqual(len(context['chunks']),1)
        self.assertEqual(context['chunks'][0].selected_ids,['doc/par-6','doc/par-7'])
        self.assertNotIn('doc/par-24',context['chunks'][0].selected_ids)

    def test_stale_or_duplicate_selection_is_refused_instead_of_resampling(self):
        for ids in [['doc/art-12'],['doc/art-1','doc/art-1'],['missing']]:
            with self.assertRaises(HTTPException):
                rx.plan_request(eu(),rx.RuleExtractionRequest(sampleChunks=1,sampleArticleIds=ids))

    def test_changed_eligibility_does_not_silently_replace_preview_articles(self):
        from odos.llm.sampling import sample_groups
        from odos.llm_input.artifacts import build_inputs
        legal=eu();scoped=build_inputs(legal)[1]
        original=rule('accepted','doc/art-1')
        with self.assertRaises(HTTPException) as raised:
            sample_groups(scoped,{'rules':[original]},{'rules':{'accepted':entry(original,'accepted')}},
                          1,selected_ids=['doc/art-1','doc/art-2'])
        self.assertEqual(raised.exception.status_code,409)

    def test_all_four_articles_are_sent_together_in_one_model_call(self):
        class Model:
            config=BedrockConfig()
            def __init__(self):self.payloads=[]
            def converse(self,system,user,**kwargs):
                self.payloads.append(json.loads(user.split('\n',1)[1]))
                return BedrockResponse('{"rules":[]}','end_turn',100,5,1,self.config.model_id)
        legal=eu();request=rx.RuleExtractionRequest(sampleChunks=1,sampleSeed=3)
        context=rx.plan_request(legal,request);model=Model()
        result=extract_document(legal,client=model,planned_chunks=context['chunks'])
        self.assertEqual(len(model.payloads),1)
        self.assertEqual(len([n for n in _walk(model.payloads[0]['target']['structure']) if n['type']=='article']),4)
        self.assertEqual(result.generation['workflow']['plannedChunks'],1)
