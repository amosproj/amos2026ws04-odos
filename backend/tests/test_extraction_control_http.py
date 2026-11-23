"""Actual FastAPI handler definitions in a minimal app; no Docling/PostgreSQL/AWS."""
import ast
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI, Body, HTTPException
from fastapi.testclient import TestClient
from odos import rule_extraction_jobs as rx
from odos.artifact_names import LEGAL_JSON
from odos.llm.bedrock import BedrockConfig
from test_v2_document_input import document


class ControlHttpTests(unittest.TestCase):
    def test_preview_start_and_stop_share_one_sample_and_stop_queued_run_without_inference(self):
        source=Path(__file__).parents[1]/'src/odos/api.py'
        names={'preview_rule_extraction','start_rule_extraction','stop_rule_extraction','get_rule_extraction'}
        definitions=[node for node in ast.parse(source.read_text()).body if isinstance(node,ast.FunctionDef) and node.name in names]
        with tempfile.TemporaryDirectory() as tmp:
            storage=Path(tmp);directory=storage/'job';directory.mkdir()
            (directory/LEGAL_JSON).write_text(json.dumps(document()))
            job=SimpleNamespace(id='job',status='completed',ruleExtraction=None)
            def lookup(identifier):
                if identifier!='job':raise HTTPException(404,'Unknown job')
                return job
            submitted=[]
            app=FastAPI()
            namespace=dict(app=app,Body=Body,HTTPException=HTTPException,rx=rx,json=json,LEGAL_JSON=LEGAL_JSON,
                _lock=threading.Lock(),_storage=storage,_job=lookup,_jobs={'job':job},
                _review_db=lambda callback:callback(),_extract_rules=lambda *args:None,
                _rule_executor=SimpleNamespace(submit=lambda function,j,request:submitted.append(request)))
            exec(compile(ast.Module(body=definitions,type_ignores=[]),'extraction_http_handlers','exec'),namespace)
            with patch.object(rx,'load_bedrock_env'),patch.object(rx,'bedrock_settings',return_value=BedrockConfig()),\
                 patch.object(rx,'bedrock_client',side_effect=AssertionError('No live inference')),TestClient(app) as client:
                preview=client.post('/api/jobs/job/rule-extraction/preview',json={'sampleChunks':1})
                self.assertEqual(preview.status_code,200,preview.text)
                self.assertEqual(preview.json()['maximumModelCalls'],1)
                self.assertFalse((directory/rx.RULE_EXTRACTION_STATUS).exists())
                start=client.post('/api/jobs/job/rule-extraction',json={'sampleChunks':1})
                self.assertEqual(start.status_code,202,start.text)
                self.assertEqual(len(submitted[0]._context['chunks']),1)
                stop=client.post('/api/jobs/job/rule-extraction/stop')
                self.assertEqual(stop.status_code,202,stop.text)
                self.assertTrue(stop.json()['stopRequested'])
                self.assertTrue((directory/rx.STOP_FILE).exists())
                final=rx.run(directory,submitted[0],job.ruleExtraction)
                self.assertEqual(final.status,'cancelled')
                self.assertFalse((directory/'rules.json').exists())
                job.ruleExtraction=final
                self.assertEqual(client.post('/api/jobs/job/rule-extraction/stop').status_code,409)
                self.assertEqual(client.post('/api/jobs/unknown/rule-extraction/stop').status_code,404)
