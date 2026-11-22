"""Amazon Bedrock client: configuration, authentication, model selection, retries, error mapping and malformed responses.

No test talks to AWS. The authentication and retry tests drive a real boto3 client and intercept its HTTP request with
botocore's `before-send` hook (so the real signing, endpoint and retry code run); the other tests use a fake client.
"""

import json

import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError

from odos import cli
from odos.llm.bedrock import (
    API_KEY_ENV,
    ENV_FILE_VAR,
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    BedrockAborted,
    BedrockAuthError,
    BedrockClient,
    BedrockConfig,
    BedrockConfigError,
    BedrockContextLimitError,
    BedrockError,
    BedrockRequestError,
    BedrockResponseError,
    BedrockThrottledError,
    BedrockTimeoutError,
    BedrockUnavailableError,
    find_env_file,
    load_bedrock_env,
    parse_env_line,
)

FAKE_KEY = "bedrock-api-key-FAKE-for-tests-only"
OK_BODY = {
    "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
    "metrics": {"latencyMs": 321},
}


@pytest.fixture(autouse=True)
def _no_ambient_aws(monkeypatch, tmp_path):
    """Tests never see the developer's AWS settings or .env and never probe for instance metadata."""
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "no-such.env"))
    for name in list(__import__("os").environ):
        if name.startswith("AWS_") or name.startswith("ODOS_BEDROCK_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setattr("botocore.endpoint.time.sleep", lambda _s: None)  # no real retry back-off


class _Raw:
    def __init__(self, body: bytes):
        self._body = body

    def stream(self, *args, **kwargs):
        yield self._body


def http_response(status: int, body: dict, error_type: str | None = None) -> AWSResponse:
    headers = {"content-type": "application/json"}
    if error_type:
        headers["x-amzn-ErrorType"] = error_type
    return AWSResponse("https://example.invalid", status, headers, _Raw(json.dumps(body).encode()))


def real_client(monkeypatch, responses: list[AWSResponse], **config) -> tuple[BedrockClient, list]:
    """A BedrockClient with a real boto3 client whose HTTP layer returns `responses` in turn and records the requests."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    seen: list = []

    def before_send(request, **kwargs):
        seen.append(request)
        return responses[min(len(seen), len(responses)) - 1]

    client = BedrockClient(BedrockConfig(**config))
    client.client.meta.events.register("before-send.bedrock-runtime.Converse", before_send)
    return client, seen


class FakeBoto:
    """Stands in for the boto3 client: returns or raises what it is given."""

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def client_error(code: str, message: str = "boom", status: int = 400) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}, "ResponseMetadata": {"HTTPStatusCode": status}}, "Converse")


def converse_with(error=None, result=None, **config) -> BedrockClient:
    return BedrockClient(BedrockConfig(**config), client=FakeBoto(result=result, error=error))


# ── configuration and model selection ────────────────────────────────────────────────────────────────────────────────


def test_defaults_are_frankfurt_and_the_eu_inference_profile():
    cfg = BedrockConfig.from_env({})
    assert cfg.region == DEFAULT_REGION == "eu-central-1"
    # in eu-central-1 the base model ID has no in-region support (AWS model card), so the default is the geo profile
    assert cfg.model_id == DEFAULT_MODEL_ID == "eu.anthropic.claude-sonnet-4-6"


def test_environment_overrides_every_setting():
    cfg = BedrockConfig.from_env({
        "ODOS_BEDROCK_REGION": "eu-west-1", "ODOS_BEDROCK_MODEL_ID": "global.anthropic.claude-sonnet-4-6",
        "ODOS_BEDROCK_MAX_TOKENS": "4000", "ODOS_BEDROCK_TEMPERATURE": "0.2", "ODOS_BEDROCK_CONNECT_TIMEOUT_SECONDS": "5",
        "ODOS_BEDROCK_READ_TIMEOUT_SECONDS": "60", "ODOS_BEDROCK_MAX_ATTEMPTS": "5", "ODOS_BEDROCK_CONTEXT_TOKENS": "200000"})
    assert (cfg.region, cfg.model_id) == ("eu-west-1", "global.anthropic.claude-sonnet-4-6")
    assert (cfg.max_tokens, cfg.temperature, cfg.connect_timeout, cfg.read_timeout, cfg.max_attempts, cfg.context_tokens) == (
        4000, 0.2, 5.0, 60.0, 5, 200000)


def test_blank_values_fall_back_to_the_defaults():
    assert BedrockConfig.from_env({"ODOS_BEDROCK_MODEL_ID": "  ", "ODOS_BEDROCK_MAX_TOKENS": ""}) == BedrockConfig()


@pytest.mark.parametrize("name, value", [("ODOS_BEDROCK_MAX_TOKENS", "many"), ("ODOS_BEDROCK_MAX_TOKENS", "0"),
                                         ("ODOS_BEDROCK_MAX_ATTEMPTS", "0"), ("ODOS_BEDROCK_READ_TIMEOUT_SECONDS", "-3")])
def test_invalid_numbers_are_refused_with_the_variable_name(name, value):
    with pytest.raises(BedrockConfigError, match=name):
        BedrockConfig.from_env({name: value})


def test_the_configured_model_and_limits_are_sent(monkeypatch):
    fake = FakeBoto(result=OK_BODY)
    client = BedrockClient(BedrockConfig(model_id="eu.anthropic.claude-sonnet-4-6", max_tokens=1234, temperature=0.0), client=fake)
    client.converse("be brief", "hello")
    sent = fake.calls[0]
    assert sent["modelId"] == "eu.anthropic.claude-sonnet-4-6"
    assert sent["system"] == [{"text": "be brief"}]
    assert sent["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]
    assert sent["inferenceConfig"] == {"maxTokens": 1234, "temperature": 0.0}


def test_per_call_limits_override_the_configuration():
    fake = FakeBoto(result=OK_BODY)
    BedrockClient(BedrockConfig(max_tokens=1000), client=fake).converse("s", "u", max_tokens=16, temperature=0.5)
    assert fake.calls[0]["inferenceConfig"] == {"maxTokens": 16, "temperature": 0.5}


# ── authentication ────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_missing_api_key_is_a_configuration_error_before_any_request(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(API_KEY_ENV, value)
    with pytest.raises(BedrockConfigError, match=API_KEY_ENV):
        BedrockClient(BedrockConfig()).converse("s", "u")


def test_the_api_key_is_sent_as_a_bearer_token_to_the_configured_region_and_model(monkeypatch):
    client, seen = real_client(monkeypatch, [http_response(200, OK_BODY)])
    response = client.converse("system text", "user text")

    assert response.text == "ok"
    assert len(seen) == 1
    request = seen[0]
    authorization = request.headers["Authorization"]  # botocore reads AWS_BEARER_TOKEN_BEDROCK itself
    assert (authorization.decode() if isinstance(authorization, bytes) else authorization) == f"Bearer {FAKE_KEY}"
    assert request.url == "https://bedrock-runtime.eu-central-1.amazonaws.com/model/eu.anthropic.claude-sonnet-4-6/converse"
    body = json.loads(request.body)
    assert body["messages"][0]["content"][0]["text"] == "user text"
    assert body["inferenceConfig"]["maxTokens"] == 32000


def test_region_and_model_follow_the_configuration(monkeypatch):
    client, seen = real_client(monkeypatch, [http_response(200, OK_BODY)], region="eu-west-1", model_id="global.anthropic.claude-sonnet-4-6")
    client.converse("s", "u")
    assert seen[0].url == "https://bedrock-runtime.eu-west-1.amazonaws.com/model/global.anthropic.claude-sonnet-4-6/converse"


def test_the_api_key_never_appears_in_an_error_message(monkeypatch):
    client = converse_with(error=client_error("ValidationException", f"bad request for {FAKE_KEY}"))
    client._environ = {API_KEY_ENV: FAKE_KEY}
    with pytest.raises(BedrockRequestError) as info:
        client.converse("s", "u")
    assert FAKE_KEY not in str(info.value)
    assert "***" in str(info.value)


# ── response ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_response_is_parsed():
    response = converse_with(result=OK_BODY).converse("s", "u")
    assert (response.text, response.stop_reason, response.input_tokens, response.output_tokens, response.latency_ms) == ("ok", "end_turn", 12, 3, 321)
    assert response.model_id == DEFAULT_MODEL_ID
    assert not response.truncated


def test_text_blocks_are_joined_and_reasoning_blocks_are_ignored():
    body = {**OK_BODY, "output": {"message": {"role": "assistant", "content": [
        {"reasoningContent": {"reasoningText": {"text": "thinking"}}}, {"text": "a"}, {"text": "b"}]}}}
    assert converse_with(result=body).converse("s", "u").text == "ab"


def test_a_cut_off_answer_is_flagged():
    assert converse_with(result={**OK_BODY, "stopReason": "max_tokens"}).converse("s", "u").truncated


@pytest.mark.parametrize("body", [
    {},
    {"stopReason": "end_turn"},
    {"output": {"message": {}}, "stopReason": "end_turn"},
    {"output": {"message": {"content": "text"}}, "stopReason": "end_turn"},
    {"output": {"message": {"content": [{"toolUse": {}}]}}, "stopReason": "end_turn"},
    {"output": {"message": {"content": [{"text": "  "}]}}, "stopReason": "end_turn"},
    {"output": {"message": {"content": [{"text": "x"}]}}, "stopReason": "content_filtered"},
    {"output": {"message": {"content": [{"text": "x"}]}}, "stopReason": "guardrail_intervened"},
    None,
])
def test_malformed_responses_are_response_errors(body):
    with pytest.raises(BedrockResponseError):
        converse_with(result=body).converse("s", "u")


# ── errors ────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("error, expected", [
    (client_error("AccessDeniedException", "no access", 403), BedrockAuthError),
    (client_error("ExpiredTokenException", "expired", 400), BedrockAuthError),
    (client_error("UnrecognizedClientException", "bad token", 403), BedrockAuthError),
    (client_error("Whatever", "unauthorized", 401), BedrockAuthError),
    (client_error("ThrottlingException", "slow down", 429), BedrockThrottledError),
    (client_error("ServiceQuotaExceededException", "quota", 400), BedrockThrottledError),
    (client_error("ModelTimeoutException", "model timed out", 408), BedrockTimeoutError),
    (client_error("ServiceUnavailableException", "down", 503), BedrockUnavailableError),
    (client_error("InternalServerException", "oops", 500), BedrockUnavailableError),
    (client_error("ModelNotReadyException", "warming up", 429), BedrockUnavailableError),
    (client_error("ModelErrorException", "model failed", 424), BedrockUnavailableError),
    (client_error("ValidationException", "malformed input", 400), BedrockRequestError),
    (client_error("ResourceNotFoundException", "no such model", 404), BedrockRequestError),
    (client_error("SomethingNew", "?", 418), BedrockError),
])
def test_aws_errors_are_mapped_to_typed_errors(error, expected):
    with pytest.raises(expected) as info:
        converse_with(error=error).converse("s", "u")
    assert type(info.value) is expected
    assert info.value.code == error.response["Error"]["Code"]


def test_a_too_long_input_is_a_context_limit_error():
    error = client_error("ValidationException", "Input is too long for requested model.")
    with pytest.raises(BedrockContextLimitError):
        converse_with(error=error).converse("s", "u")


def test_the_base_model_id_error_points_to_the_inference_profile():
    error = client_error("ValidationException", "Invocation of model ID anthropic.claude-sonnet-4-6 with on-demand throughput "
                         "isn't supported. Retry your request with the ID or ARN of an inference profile that contains this model.")
    with pytest.raises(BedrockRequestError, match="eu.anthropic.claude-sonnet-4-6"):
        converse_with(error=error, model_id="anthropic.claude-sonnet-4-6").converse("s", "u")


@pytest.mark.parametrize("error", [ReadTimeoutError(endpoint_url="https://x"), ConnectTimeoutError(endpoint_url="https://x")])
def test_timeouts_are_timeout_errors(error):
    with pytest.raises(BedrockTimeoutError, match="ODOS_BEDROCK_READ_TIMEOUT_SECONDS"):
        converse_with(error=error).converse("s", "u")


def test_no_connection_is_an_unavailable_error():
    with pytest.raises(BedrockUnavailableError, match="eu-central-1"):
        converse_with(error=EndpointConnectionError(endpoint_url="https://x")).converse("s", "u")


# ── diagnostics: the facts of a failure without its content ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["ConnectionClosedError", "SSLError", "ProxyConnectionError", "ResponseStreamingError"])
def test_transient_connection_failures_are_unavailable_not_a_rejected_request(name):
    import botocore.exceptions as be

    error = {"ConnectionClosedError": lambda: be.ConnectionClosedError(endpoint_url="https://x"),
             "SSLError": lambda: be.SSLError(endpoint_url="https://x", error="handshake"),
             "ProxyConnectionError": lambda: be.ProxyConnectionError(proxy_url="http://p"),
             "ResponseStreamingError": lambda: be.ResponseStreamingError(error="cut off")}[name]()
    with pytest.raises(BedrockUnavailableError) as info:
        converse_with(error=error, max_attempts=3).converse("s", "u")
    assert type(info.value) is BedrockUnavailableError and not isinstance(info.value, BedrockRequestError)
    assert info.value.diagnostics() == {"cause": name}
    assert "3 attempt(s)" in str(info.value)


def test_a_request_that_cannot_be_built_is_still_a_request_error():
    from botocore.exceptions import ParamValidationError

    with pytest.raises(BedrockRequestError) as info:
        converse_with(error=ParamValidationError(report="bad parameter")).converse("s", "u")
    assert info.value.diagnostics() == {"cause": "ParamValidationError"}


def test_a_client_error_reports_its_aws_code_http_status_and_retries_but_not_its_message():
    error = ClientError({"Error": {"Code": "ValidationException", "Message": "secret document text 4711"},
                         "ResponseMetadata": {"HTTPStatusCode": 400, "RetryAttempts": 2}}, "Converse")
    with pytest.raises(BedrockRequestError) as info:
        converse_with(error=error).converse("s", "u")
    assert info.value.diagnostics() == {"awsCode": "ValidationException", "httpStatus": 400, "retryAttempts": 2}
    assert "4711" not in str(info.value.diagnostics())


def test_a_connection_error_without_a_response_reports_the_client_side_error_class():
    from botocore.exceptions import ConnectionClosedError

    with pytest.raises(BedrockUnavailableError) as info:
        converse_with(error=ConnectionClosedError(endpoint_url="https://x")).converse("s", "u")
    assert info.value.diagnostics() == {"cause": "ConnectionClosedError"}


@pytest.mark.parametrize("error, cause", [(ReadTimeoutError(endpoint_url="https://x"), "ReadTimeoutError"),
                                          (EndpointConnectionError(endpoint_url="https://x"), "EndpointConnectionError")])
def test_timeouts_and_unreachable_endpoints_report_their_class(error, cause):
    with pytest.raises(BedrockError) as info:
        converse_with(error=error).converse("s", "u")
    assert info.value.diagnostics() == {"cause": cause}


def test_diagnostics_drop_anything_that_is_not_a_plain_code_or_number():
    e = BedrockError("m", code="text with spaces and a secret ABSK123", http_status=True, cause="x" * 200, retry_attempts=-1)
    assert e.diagnostics() == {}
    assert BedrockError("m").diagnostics() == {}


# ── timeouts and retries (real botocore retry handling) ──────────────────────────────────────────────────────────────


def test_the_configured_timeouts_and_attempts_reach_boto3(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    client = BedrockClient(BedrockConfig(connect_timeout=7, read_timeout=42, max_attempts=4)).client
    assert client.meta.config.connect_timeout == 7
    assert client.meta.config.read_timeout == 42
    assert client.meta.config.retries == {"total_max_attempts": 4, "mode": "standard"}
    assert client.meta.region_name == "eu-central-1"


def test_throttling_is_retried_until_the_attempts_are_used_up(monkeypatch):
    throttled = {"message": "Too many requests"}
    client, seen = real_client(monkeypatch, [http_response(429, throttled, "ThrottlingException")], max_attempts=3)
    with pytest.raises(BedrockThrottledError):
        client.converse("s", "u")
    assert len(seen) == 3


def test_a_transient_server_error_is_retried_and_then_succeeds(monkeypatch):
    client, seen = real_client(monkeypatch, [http_response(503, {"message": "unavailable"}, "ServiceUnavailableException"),
                                             http_response(200, OK_BODY)], max_attempts=3)
    assert client.converse("s", "u").text == "ok"
    assert len(seen) == 2


def test_an_authentication_error_is_not_retried(monkeypatch):
    client, seen = real_client(monkeypatch, [http_response(403, {"message": "denied"}, "AccessDeniedException")], max_attempts=3)
    with pytest.raises(BedrockAuthError):
        client.converse("s", "u")
    assert len(seen) == 1


def test_a_validation_error_is_not_retried(monkeypatch):
    client, seen = real_client(monkeypatch, [http_response(400, {"message": "bad"}, "ValidationException")], max_attempts=3)
    with pytest.raises(BedrockRequestError):
        client.converse("s", "u")
    assert len(seen) == 1


def test_a_response_that_is_not_json_is_an_error_not_a_crash(monkeypatch):
    raw = AWSResponse("https://example.invalid", 200, {"content-type": "application/json"}, _Raw(b"<html>proxy error</html>"))
    client, _ = real_client(monkeypatch, [raw])
    with pytest.raises(BedrockError):
        client.converse("s", "u")


def test_constructing_the_wrapper_needs_no_api_key_and_creates_no_boto_client():
    assert BedrockClient(BedrockConfig())._client is None


# ── .env loading (the Bedrock settings only) ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("line, expected", [
    ("AWS_BEARER_TOKEN_BEDROCK=abc", ("AWS_BEARER_TOKEN_BEDROCK", "abc")),
    ("export AWS_BEARER_TOKEN_BEDROCK=abc", ("AWS_BEARER_TOKEN_BEDROCK", "abc")),
    ("  AWS_BEARER_TOKEN_BEDROCK = abc  ", ("AWS_BEARER_TOKEN_BEDROCK", "abc")),
    ('AWS_BEARER_TOKEN_BEDROCK="abc def"', ("AWS_BEARER_TOKEN_BEDROCK", "abc def")),
    ("AWS_BEARER_TOKEN_BEDROCK='abc'", ("AWS_BEARER_TOKEN_BEDROCK", "abc")),
    ("AWS_BEARER_TOKEN_BEDROCK=abc # a comment", ("AWS_BEARER_TOKEN_BEDROCK", "abc")),
    ("AWS_BEARER_TOKEN_BEDROCK=ab#c", ("AWS_BEARER_TOKEN_BEDROCK", "ab#c")),  # only " #" starts a comment
    ("AWS_BEARER_TOKEN_BEDROCK=a=b==", ("AWS_BEARER_TOKEN_BEDROCK", "a=b==")),
    ("AWS_BEARER_TOKEN_BEDROCK=", ("AWS_BEARER_TOKEN_BEDROCK", "")),
    ("# AWS_BEARER_TOKEN_BEDROCK=abc", None),
    ("", None),
    ("not a setting", None),
])
def test_env_lines_are_parsed_like_compose_reads_them(line, expected):
    assert parse_env_line(line) == expected


def write_env(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_the_bedrock_settings_of_the_env_file_are_applied_and_nothing_else(tmp_path):
    env_file = write_env(tmp_path / ".env", f"POSTGRES_PASSWORD=secret\n{API_KEY_ENV}={FAKE_KEY}\nODOS_BEDROCK_REGION=eu-west-1\nAWS_SECRET_ACCESS_KEY=x\n")
    environ = {ENV_FILE_VAR: str(env_file)}
    result = load_bedrock_env(environ)
    assert result.path == env_file
    assert set(result.loaded) == set(result.present) == {API_KEY_ENV, "ODOS_BEDROCK_REGION"}
    assert environ[API_KEY_ENV] == FAKE_KEY and environ["ODOS_BEDROCK_REGION"] == "eu-west-1"
    assert "POSTGRES_PASSWORD" not in environ and "AWS_SECRET_ACCESS_KEY" not in environ


def test_a_non_empty_variable_from_the_shell_wins_over_the_env_file(tmp_path):
    env_file = write_env(tmp_path / ".env", f"{API_KEY_ENV}=from-file\nODOS_BEDROCK_REGION=eu-west-1\n")
    environ = {ENV_FILE_VAR: str(env_file), API_KEY_ENV: "from-shell"}
    result = load_bedrock_env(environ)
    assert environ[API_KEY_ENV] == "from-shell"
    assert environ["ODOS_BEDROCK_REGION"] == "eu-west-1"
    assert result.loaded == ("ODOS_BEDROCK_REGION",) and API_KEY_ENV in result.present


def test_a_blank_variable_from_the_shell_is_replaced_by_the_env_file(tmp_path):
    environ = {ENV_FILE_VAR: str(write_env(tmp_path / ".env", f"{API_KEY_ENV}=from-file\n")), API_KEY_ENV: "  "}
    load_bedrock_env(environ)
    assert environ[API_KEY_ENV] == "from-file"


def test_an_empty_setting_in_the_env_file_is_not_applied(tmp_path):
    environ = {ENV_FILE_VAR: str(write_env(tmp_path / ".env", f"{API_KEY_ENV}=\n"))}
    result = load_bedrock_env(environ)
    assert result.present == () and API_KEY_ENV not in environ  # "is the key really in the file?" is answerable from `present`


def test_an_env_file_with_a_bom_and_windows_line_endings_is_read(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xef\xbb\xbf" + f"{API_KEY_ENV}=abc\r\nODOS_BEDROCK_REGION=eu-west-1\r\n".encode())
    environ = {ENV_FILE_VAR: str(env_file)}
    load_bedrock_env(environ)
    assert environ[API_KEY_ENV] == "abc" and environ["ODOS_BEDROCK_REGION"] == "eu-west-1"


def test_no_env_file_changes_nothing(tmp_path):
    environ = {ENV_FILE_VAR: str(tmp_path / "missing.env")}
    result = load_bedrock_env(environ)
    assert (result.path, result.present, result.loaded) == (None, (), ()) and environ == {ENV_FILE_VAR: str(tmp_path / "missing.env")}


def test_an_unreadable_env_file_is_not_a_crash(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xff\xfe\x00bad")
    assert load_bedrock_env({ENV_FILE_VAR: str(env_file)}).loaded == ()


def test_the_env_file_is_searched_in_the_working_directory_and_its_parents(tmp_path):
    write_env(tmp_path / ".env", "X=1\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_env_file(nested, {}) == (tmp_path / ".env").resolve()


def test_the_command_reads_the_key_from_the_env_file_and_never_prints_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(ENV_FILE_VAR, str(write_env(tmp_path / ".env", f"{API_KEY_ENV}={FAKE_KEY}\n")))
    monkeypatch.setenv(API_KEY_ENV, "")  # restored afterwards: the loader writes to os.environ
    seen = {}

    class FakeBedrockClient:
        config = BedrockConfig()

        def converse(self, system, user, **kwargs):
            seen["key_in_environment"] = __import__("os").environ.get(API_KEY_ENV) == FAKE_KEY
            return __import__("odos.llm.bedrock", fromlist=["BedrockResponse"]).BedrockResponse("ok", "end_turn", 5, 1, 100, DEFAULT_MODEL_ID)

    monkeypatch.setattr("odos.llm.bedrock.BedrockClient", FakeBedrockClient)
    assert cli.main(["bedrock-check"]) == 0
    out = capsys.readouterr()
    assert seen == {"key_in_environment": True}
    assert FAKE_KEY not in out.out + out.err
    assert "1 Bedrock setting(s) applied" in out.out and str(tmp_path / ".env") in out.out


def test_the_command_says_when_the_env_file_has_no_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(ENV_FILE_VAR, str(write_env(tmp_path / ".env", "POSTGRES_USER=odos\nPOSTGRES_PASSWORD=pw\n")))
    assert cli.main(["bedrock-check"]) == 2
    err = capsys.readouterr().err
    assert API_KEY_ENV in err and "is the file saved" in err
    assert "pw" not in err


def test_abort_closes_the_connection_and_does_not_send_the_request_again():
    sent: list[object] = []

    class Fake:
        def converse(self, **kwargs):
            sent.append(kwargs)

        def close(self):
            sent.append("closed")

    client = BedrockClient(config=BedrockConfig(), client=Fake())
    assert client._stop_retry() is None  # a live request may still be retried
    client.abort()
    assert sent == ["closed"]
    assert client._stop_retry() is False  # botocore must not send it again
    with pytest.raises(BedrockAborted):
        client.converse("system", "user")
    assert sent == ["closed"]
