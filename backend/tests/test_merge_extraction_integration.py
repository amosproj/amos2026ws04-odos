"""Integration of preview/incremental extraction with develop's safe publication and cancellation.

Model and document extraction are fakes. These tests never contact AWS or require PostgreSQL.
"""
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from odos import api, rule_extraction_jobs as rx
from odos.artifact_names import LEGAL_JSON, RULE_JSON
from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.rule_extraction import _walk
from odos.pipeline import Outcome, PipelineResult
from test_extraction_controls import rule
from test_v2_document_input import document


class Model:
    config = BedrockConfig()

    def __init__(self, gate=None):
        self.entered = threading.Event()
        self.gate = gate
        self.calls = []

    def converse(self, system, user, **kwargs):
        payload = json.loads(user.split("\n", 1)[1])
        self.calls.append(payload)
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5), "test model was not released"
        node = next(n for n in _walk(payload["target"]["structure"]) if n.get("text"))
        return BedrockResponse(json.dumps({"rules": [rule(node["id"], node["id"])]}),
                               "end_turn", 100, 50, 1, self.config.model_id)


class MergeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.legal = document()
        def pipeline(pdf, out_dir, progress):
            (out_dir / LEGAL_JSON).write_text(json.dumps(self.legal), encoding="utf-8")
            return PipelineResult(outcome=Outcome.COMPLETED, summary={})
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"ODOS_DATABASE_ENABLED": "0", "ODOS_STORAGE_DIR": ""}).start()
        patch.object(api, "run_pipeline", side_effect=pipeline).start()
        patch.object(rx, "bedrock_settings", return_value=BedrockConfig()).start()
        patch.object(api.rv, "review_state", return_value={"rules": {}}).start()
        self.client = TestClient(api.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        response = self.client.post("/api/jobs", files={"file": ("test.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
        self.job_id = response.json()["id"]
        self.url = f"/api/jobs/{self.job_id}/rule-extraction"
        for _ in range(250):
            job = self.client.get(f"/api/jobs/{self.job_id}").json()
            if job["status"] not in ("queued", "processing"):
                break
            time.sleep(.01)
        self.assertEqual(job["status"], "completed", job)

    def wait(self):
        for _ in range(500):
            state = self.client.get(self.url).json()
            if state["status"] not in ("queued", "running"):
                return state
            time.sleep(.01)
        self.fail("extraction did not finish")

    def start(self, model, **body):
        patch.object(rx, "bedrock_client", return_value=model).start()
        response = self.client.post(self.url, json=body)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_preview_selection_stage_callbacks_and_download_use_v2(self):
        model = Model()
        patch.object(rx, "load_bedrock_env").start()
        preview = self.client.post(self.url + "/preview", json={"articleIds": ["doc/par-6"]})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["maximumModelCalls"], 1)
        self.assertEqual(model.calls, [])
        queued = self.start(model, articleIds=["doc/par-6"], maxModelCalls=1)
        self.assertTrue(queued["runId"])
        finished = self.wait()
        self.assertEqual(finished["status"], "completed", finished)
        self.assertTrue(finished["externalRequestStarted"])
        self.assertIsNone(finished["stage"])
        self.assertEqual(len(model.calls), 1)
        self.assertNotIn('"germanType"', json.dumps(model.calls))
        self.assertNotIn('"marker"', json.dumps(model.calls))
        response = self.client.get(f"/api/jobs/{self.job_id}/files/{RULE_JSON}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["_generation"]["selection"]["articleIds"], ["doc/par-6"])

    def test_cancel_discards_new_result_and_preserves_previous_file(self):
        self.start(Model(), articleIds=["doc/par-6"])
        self.assertEqual(self.wait()["status"], "completed")
        path = api._storage / self.job_id / RULE_JSON
        before = path.read_bytes()
        gate = threading.Event()
        self.addCleanup(gate.set)
        model = Model(gate)
        self.start(model, articleIds=["doc/par-7"])
        try:
            self.assertTrue(model.entered.wait(5))
            response = self.client.post(self.url + "/cancel")
            self.assertTrue(response.json()["cancelRequested"])
        finally:
            gate.set()
        finished = self.wait()
        self.assertEqual(finished["status"], "cancelled", finished)
        self.assertTrue(finished["externalRequestStarted"])
        self.assertEqual(path.read_bytes(), before)

    def test_stop_keeps_finished_response_as_partial(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        model = Model(gate)
        self.start(model, articleIds=["doc/par-6"])
        try:
            self.assertTrue(model.entered.wait(5))
            response = self.client.post(self.url + "/stop")
            self.assertEqual(response.status_code, 202)
            self.assertTrue(response.json()["stopRequested"])
        finally:
            gate.set()
        finished = self.wait()
        self.assertEqual(finished["status"], "completed", finished)
        self.assertTrue(finished["stopRequested"])
        self.assertTrue(finished["modelOutput"]["partial"])
        self.assertEqual(len(json.loads((api._storage / self.job_id / RULE_JSON).read_text())["rules"]), 1)

    def test_restart_has_new_identity_and_appends_to_saved_rules(self):
        first = self.start(Model(), articleIds=["doc/par-6"])
        self.assertEqual(self.wait()["status"], "completed")
        second = self.start(Model(), articleIds=["doc/par-7"])
        self.assertNotEqual(first["runId"], second["runId"])
        self.assertEqual(self.wait()["status"], "completed")
        result = json.loads((api._storage / self.job_id / RULE_JSON).read_text())
        self.assertEqual(len(result["rules"]), 2)

    def test_unknown_and_excluded_scopes_are_distinguished(self):
        response = self.client.post(self.url, json={"elementIds": ["doc/par-999"]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["X-ODOS-Error"], "invalid_scope")
        response = self.client.post(self.url, json={"elementIds": ["doc/par-24"]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["X-ODOS-Error"], "nothing_to_extract")
