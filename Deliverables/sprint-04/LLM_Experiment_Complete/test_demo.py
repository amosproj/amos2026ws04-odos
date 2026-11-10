"""用模拟模型响应测试 FastAPI 任务和 DeepSeek 接口。"""

import json as jsonlib
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

# TestClient 在当前进程里调用真实的 FastAPI 路由。模型回复由测试安排。
from app import app, jobs
from verifier import EX, ModelResult


class VerificationTest(unittest.TestCase):
    # 每次测试先清空任务表，免得上个测试留下的任务来串门。
    def setUp(self):
        jobs.clear()
        self.client = TestClient(app)

    # 和 Swagger 上操作一样：先取样例，再把返回的 JSON 提交成任务。
    def submit(self, name):
        example = self.client.get(f"/api/examples/{name}")
        self.assertEqual(example.status_code, 200)
        return self.client.post("/api/jobs", json=example.json())

    # 同一扇窗提交两次，只改模型对宽度的判断。
    # 如果报告也跟着变，就说明后台确实采用了模型的判断。
    def test_model_verdict_drives_result(self):
        # 给测试设置一套假的服务配置。这把 Key 最大的安全优势是它根本不能用。
        with patch.dict(os.environ, {"ODOS_LLM_MODEL": "test-model", "DEEPSEEK_API_KEY": "dummy-key", "DEEPSEEK_BASE_URL": "https://gateway.example/v1"}):
            for width_verdict in ("pass", "fail"):
                with self.subTest(verdict=width_verdict):
                    # 替代真实的 HTTP 调用，检查程序本来会发给 DeepSeek 什么。
                    def model_reply(url, *, headers, json, timeout):
                        self.assertEqual(url, "https://gateway.example/v1/chat/completions")
                        self.assertEqual(headers["Authorization"], "Bearer dummy-key")
                        self.assertEqual(json["response_format"], {"type": "json_object"})
                        self.assertEqual(json["model"], "test-model")
                        # 拆开请求里的用户消息，核对条款编号和窗宽。
                        context = jsonlib.loads(json["messages"][1]["content"])
                        self.assertEqual(context["source_clause"], "37.5")
                        self.assertEqual(context["facts"]["clearWidthM"][0]["value"], "0.90")
                        # 给每条规则返回一项结果。两轮测试只有宽度结论不同。
                        findings = [
                            {"rule_id": rule["id"],
                             "verdict": "not_applicable" if rule["id"] == "roof_distance" else
                             width_verdict if rule["id"] == "clearWidthM" else "pass",
                             "explanation": "Simulated model judgment.",
                             "evidence_fields": ["inRoofSlopeOrRoofStructure"] if rule["id"] == "roof_distance"
                             else [rule["id"]]}
                            for rule in context["rules"]
                        ]
                        # 模拟 DeepSeek 的响应结构，让真正的解析代码照常上班。
                        return httpx.Response(
                            200,
                            json={"choices": [{"message": {"content": jsonlib.dumps({"findings": findings})}}]},
                            request=httpx.Request("POST", url),
                        )

                    # 只替换这次请求里的 HTTP 调用，其余任务流程照常执行。
                    with patch("verifier.httpx.post", side_effect=model_reply):
                        queued = self.submit("valid_boundary")
                    # 检查任务是否接收成功，并确认报告包含模型结论和原始 RDF 证据。
                    self.assertEqual(queued.status_code, 202)
                    path = f"/api/jobs/{queued.json()['id']}"
                    self.assertEqual(self.client.get(path).json()["status"], "completed")
                    report = self.client.get(path + "/files/verification_report.json").json()
                    self.assertEqual(report["verdict"], width_verdict)
                    self.assertEqual(report["engine"], "deepseek")
                    self.assertEqual(report["subject"], str(EX.valid_boundary))
                    self.assertEqual(report["findings"][0]["evidence"]["clearWidthM"][0]["value"], "0.90")
                    # 删除已结束的任务，预期收到 HTTP 204。一声不吭地说再见。
                    self.assertEqual(self.client.delete(path).status_code, 204)

    # 没有验证对象时应直接拒绝。模型再自信，也验不了一扇不存在的窗。
    def test_no_target_never_calls_model(self):
        with patch("verifier.httpx.post") as post:
            response = self.submit("no_target")
        self.assertEqual(response.status_code, 422)
        post.assert_not_called()

    # JSON 格式合法也可能漏项。答了一道题不算交完卷。
    def test_incomplete_response_fails_job(self):
        invalid = ModelResult.model_validate({"findings": [{
            "rule_id": "clearWidthM", "verdict": "pass",
            "explanation": "Incomplete model response.", "evidence_fields": ["clearWidthM"],
        }]})
        # 直接注入一份不完整的模型回复，专门测试是否检查了每条规则都有结果。
        with patch("verifier.ask_deepseek", return_value=invalid):
            queued = self.submit("valid_boundary")
        path = f"/api/jobs/{queued.json()['id']}"
        # 任务应该失败，取报告应返回 409，半份报告也不能提前交卷。
        self.assertEqual(self.client.get(path).json()["status"], "failed")
        self.assertEqual(self.client.get(path + "/files/verification_report.json").status_code, 409)


# 直接执行这个文件时，运行整套测试。
if __name__ == "__main__":
    unittest.main()
