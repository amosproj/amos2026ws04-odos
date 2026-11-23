"""Free previews and per-chunk call limits. Fake responses only; no Bedrock requests."""
import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from pydantic import ValidationError
from odos import rule_extraction_jobs as rx
from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.document_extraction import extract_document, plan_chunks, prepare_chunk
from odos.llm.extraction_workflow import extract_rules_workflow
from test_v2_document_input import document


class InvalidModel:
    config = BedrockConfig()

    def __init__(self):
        self.calls = 0

    def converse(self, *args, **kwargs):
        self.calls += 1
        return BedrockResponse('{"rules":[{"id":"invalid-rule"}]}', 'end_turn', 100, 50, 1, self.config.model_id)


class PreviewTests(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(rx.RuleExtractionRequest().maxModelCalls, 1)
        for limit in (1, 3):
            request = rx.RuleExtractionRequest(maxModelCalls=limit)
            self.assertEqual(rx.RuleExtraction.queued(request).maxModelCalls, limit)
        for invalid in (0, 2, 4, True, '3', 1.0):
            with self.assertRaises(ValidationError):
                rx.RuleExtractionRequest(maxModelCalls=invalid)

    def test_preview_matches_actual_v2_prompts_without_creating_client(self):
        legal = document(); original = copy.deepcopy(legal)
        config = BedrockConfig()
        with patch.object(rx, 'load_bedrock_env'), patch.object(rx.BedrockConfig, 'from_env', return_value=config), \
             patch.object(rx, 'bedrock_client', side_effect=AssertionError('No inference in preview')):
            result = rx.preview_request(legal, rx.RuleExtractionRequest())
        _, chunks = plan_chunks(legal)
        expected = sum(prepare_chunk(legal, c, config)[0].estimated_input_tokens for c in chunks)
        self.assertEqual(result['estimatedInitialInputTokens'], expected)
        self.assertEqual(result['chunks'], 2)  # excluded MBO section 24 is absent
        self.assertEqual(result['maximumModelCalls'], 2)
        self.assertEqual(result['maximumOutputTokens'], 2 * config.max_tokens)
        self.assertTrue(result['canStart'])
        self.assertEqual(legal, original)

    def test_three_call_preview_and_scoped_selection(self):
        with patch.object(rx, 'load_bedrock_env'), patch.object(rx.BedrockConfig, 'from_env', return_value=BedrockConfig()):
            preview = rx.preview_request(document(), rx.RuleExtractionRequest(elementIds=['doc/par-6'], maxModelCalls=3))
        self.assertEqual(preview['chunks'], 1)
        self.assertEqual(preview['maximumModelCalls'], 3)

    def test_oversize_preview_does_not_claim_ready(self):
        config = replace(BedrockConfig(), context_tokens=10)
        with patch.object(rx, 'load_bedrock_env'), patch.object(rx.BedrockConfig, 'from_env', return_value=config):
            preview = rx.preview_request(document(), rx.RuleExtractionRequest())
        self.assertFalse(preview['canStart'])
        self.assertEqual(preview['readyChunks'], 0)
        self.assertEqual(preview['blockedChunks'], 2)
        self.assertEqual(preview['maximumModelCalls'], 0)

    def test_default_stops_after_initial_response_and_keeps_validation_report(self):
        model = InvalidModel()
        result = extract_rules_workflow(document(), client=model)
        self.assertEqual(model.calls, 1)
        self.assertEqual(result.report['maxModelCalls'], 1)
        self.assertEqual(result.report['maxFeedbackRounds'], 0)
        self.assertFalse(result.report['checks']['schemaValid'])

    def test_three_calls_remain_available(self):
        model = InvalidModel()
        result = extract_rules_workflow(document(), client=model, max_model_calls=3)
        self.assertEqual(model.calls, 3)
        self.assertEqual(result.report['maxModelCalls'], 3)

    def test_document_propagates_independent_call_limits_to_each_chunk(self):
        for limit in (1, 3):
            model = InvalidModel()
            result = extract_document(document(), client=model, max_workers=1, max_model_calls=limit)
            self.assertEqual(model.calls, 2 * limit)
            self.assertEqual(result.generation['workflow']['maxModelCallsPerChunk'], limit)
            self.assertTrue(all(c['report']['maxModelCalls'] == limit for c in result.report['chunks']))

    def test_worker_passes_limit_and_does_not_overwrite_rules_when_transport_fails(self):
        import tempfile
        from pathlib import Path
        from odos.artifact_names import LEGAL_JSON, RULE_JSON
        from odos.llm.bedrock import BedrockUnavailableError
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / LEGAL_JSON).write_text(json.dumps(document()))
            (directory / RULE_JSON).write_text('previous rules')
            request = rx.RuleExtractionRequest(maxModelCalls=3)
            request._context = {"chunks": plan_chunks(document())[1], "previous": {}, "reviews": {}, "skipped": [], "eligible": 2}
            with patch.object(rx, 'bedrock_client', return_value=object()), \
                 patch.object(rx, 'extract_rules', side_effect=BedrockUnavailableError('offline')) as extract:
                state = rx.run(directory, request, rx.RuleExtraction.queued(request))
            self.assertEqual(extract.call_args.kwargs['max_model_calls'], 3)
            self.assertEqual(state.status, 'failed')
            self.assertEqual((directory / RULE_JSON).read_text(), 'previous rules')

    def test_invalid_direct_limits_rejected_before_client_use(self):
        for invalid in (0, 2, 4, True):
            with self.assertRaises(ValueError):
                extract_document(document(), max_model_calls=invalid)
            with self.assertRaises(ValueError):
                extract_rules_workflow(document(), max_model_calls=invalid)
