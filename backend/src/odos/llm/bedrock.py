"""Amazon Bedrock client (Converse API) for ODOS.

Authentication is a Bedrock API key in the environment variable ``AWS_BEARER_TOKEN_BEDROCK``. boto3/botocore reads that
variable itself and sends ``Authorization: Bearer <key>``; ODOS never reads the key's value, stores it, logs it or puts
it into an exception message. Region, model and limits come from ``ODOS_BEDROCK_*`` variables (`BedrockConfig.from_env`).

The default model is Claude Sonnet 4.6 through the EU geo inference profile ``eu.anthropic.claude-sonnet-4-6``: in
``eu-central-1`` the base model ID ``anthropic.claude-sonnet-4-6`` has no in-region support, so a profile ID is required
(AWS model card for Claude Sonnet 4.6; the profile keeps requests inside the EU).

Timeouts and retries: botocore's ``standard`` retry mode retries throttling, 5xx responses and connection/read timeouts
with exponential backoff and jitter, ``ODOS_BEDROCK_MAX_ATTEMPTS`` times in total. Whatever still fails is raised as one
of the `BedrockError` subclasses below.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ConnectionError as BotoConnectionError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)

log = logging.getLogger("odos.llm.bedrock")

API_KEY_ENV = "AWS_BEARER_TOKEN_BEDROCK"  # read by botocore, not by ODOS
DEFAULT_REGION = "eu-central-1"
DEFAULT_MODEL_ID = "eu.anthropic.claude-sonnet-4-6"
SERVICE = "bedrock-runtime"
MAX_OUTPUT_RETRIES = 1  # hard cap on paid re-requests for an unusable answer, whatever the configuration says


# ── errors ────────────────────────────────────────────────────────────────────────────────────────────────────────────


class BedrockError(Exception):
    """Base class of every error of the Bedrock integration. Messages never contain the API key."""

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None,
                 cause: str | None = None, retry_attempts: int | None = None) -> None:
        super().__init__(message)
        self.code = code  # the AWS error code, where there is one (e.g. ThrottlingException)
        self.http_status = http_status  # the HTTP status of the failed response
        self.cause = cause  # class name of the client-side error (e.g. ConnectionClosedError) when no response arrived
        self.retry_attempts = retry_attempts  # transport retries botocore made before giving up

    def diagnostics(self) -> dict[str, str | int]:
        """Only the machine-readable facts of the failure, safe to log and to report: the AWS error code, the HTTP status,
        the client-side error class and the number of transport retries. Never the message, request or response."""
        facts = {"awsCode": _safe_name(self.code), "httpStatus": _safe_int(self.http_status),
                 "cause": _safe_name(self.cause), "retryAttempts": _safe_int(self.retry_attempts)}
        return {k: v for k, v in facts.items() if v is not None}


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _safe_name(value: object) -> str | None:
    """An error code or class name; anything else (free text, a key) is dropped rather than reported."""
    return value if isinstance(value, str) and _SAFE_NAME.match(value) else None


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10_000 else None


class BedrockConfigError(BedrockError):
    """Missing or invalid configuration (no API key, malformed number, ...). Nothing was sent."""


class BedrockAuthError(BedrockError):
    """The API key was rejected, is expired, or lacks permission for the model (HTTP 401/403)."""


class BedrockThrottledError(BedrockError):
    """Rate or quota limit, still hit after all retries."""


class BedrockTimeoutError(BedrockError):
    """No (complete) answer within the connect/read timeout, still failing after all retries."""


class BedrockUnavailableError(BedrockError):
    """Bedrock or the model is temporarily unavailable (5xx, model not ready, no connection), after all retries."""


class BedrockRequestError(BedrockError):
    """Bedrock rejected the request itself: invalid model ID, model not enabled, invalid parameters."""


class BedrockContextLimitError(BedrockRequestError):
    """The input is longer than the model's context window."""


class BedrockResponseError(BedrockError):
    """The answer is malformed, empty, filtered, or cut off."""


# ── .env ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
# ODOS has no general .env loader (Docker Compose reads .env itself; locally the variables are exported). For the Bedrock
# commands only, `load_bedrock_env` reads the Bedrock settings of a .env file so that `odos bedrock-check` works without
# exporting them. It never prints or returns a value, and a non-empty variable from the shell always wins.

ENV_FILE_VAR = "ODOS_ENV_FILE"  # explicit .env path; when set, no other location is searched
REPO_ROOT = Path(__file__).resolve().parents[4]
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


@dataclass(frozen=True)
class EnvLoad:
    path: Path | None  # the .env file that was read; None if there is none
    present: tuple[str, ...]  # names of Bedrock settings with a non-empty value in that file
    loaded: tuple[str, ...]  # the part of `present` that was applied (the shell did not already set them)


def _is_bedrock_setting(name: str) -> bool:
    return name == API_KEY_ENV or name.startswith("ODOS_BEDROCK_")


def find_env_file(cwd: Path | None = None, environ: Mapping[str, str] | None = None) -> Path | None:
    """`$ODOS_ENV_FILE`, else the first `.env` in the working directory or one of its parents, else the repository's."""
    explicit = (os.environ if environ is None else environ).get(ENV_FILE_VAR)
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    start = (cwd or Path.cwd()).resolve()
    for directory in (start, *start.parents, REPO_ROOT):
        if (directory / ".env").is_file():
            return directory / ".env"
    return None


def parse_env_line(line: str) -> tuple[str, str] | None:
    """`NAME=value`, `export NAME="value"`; None for blank lines, comments and anything else."""
    if line.lstrip().startswith("#") or not (m := _ENV_LINE.match(line)):
        return None
    name, value = m.groups()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return name, value[1:-1]
    return name, re.split(r"\s+#", value, maxsplit=1)[0].strip()


def load_bedrock_env(environ: MutableMapping[str, str] | None = None, cwd: Path | None = None) -> EnvLoad:
    """Apply the Bedrock settings (`AWS_BEARER_TOKEN_BEDROCK`, `ODOS_BEDROCK_*`) of the .env file to `environ`
    (default `os.environ`), unless the shell already set them to a non-empty value. Other variables are ignored."""
    env = os.environ if environ is None else environ
    path = find_env_file(cwd, env)
    if path is None:
        return EnvLoad(None, (), ())
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return EnvLoad(path, (), ())
    present: list[str] = []
    loaded: list[str] = []
    for line in lines:
        parsed = parse_env_line(line)
        if parsed is None or not _is_bedrock_setting(parsed[0]) or not parsed[1]:
            continue
        name, value = parsed
        present.append(name)
        if not (env.get(name) or "").strip():
            env[name] = value
            loaded.append(name)
    return EnvLoad(path, tuple(present), tuple(loaded))


# ── configuration ─────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BedrockConfig:
    region: str = DEFAULT_REGION
    model_id: str = DEFAULT_MODEL_ID
    max_tokens: int = 32_000  # answer limit per request (model maximum 64k; one German § needed 17k); billed per token used
    temperature: float = 0.0  # extraction should be as repeatable as the model allows
    connect_timeout: float = 10.0  # seconds
    read_timeout: float = 600.0  # seconds; a long answer is generated before the response arrives
    max_attempts: int = 3  # total attempts per request, including the first
    context_tokens: int = 1_000_000  # the model's context window (AWS model card for Claude Sonnet 4.6)
    output_retries: int = 1  # extra model calls when an answer is not valid JSON: 0 or 1 (MAX_OUTPUT_RETRIES), never more

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BedrockConfig:
        env = os.environ if environ is None else environ

        def text(name: str, default: str) -> str:
            return (env.get(name) or "").strip() or default

        def number(name: str, default: float, kind: type, minimum: float) -> Any:
            raw = (env.get(name) or "").strip()
            if not raw:
                return default
            try:
                value = kind(raw)
            except ValueError:
                raise BedrockConfigError(f"{name} must be a number, got {raw!r}.") from None
            if value < minimum:
                raise BedrockConfigError(f"{name} must be at least {minimum}, got {raw!r}.")
            return value

        d = cls()
        return cls(
            region=text("ODOS_BEDROCK_REGION", d.region),
            model_id=text("ODOS_BEDROCK_MODEL_ID", d.model_id),
            max_tokens=number("ODOS_BEDROCK_MAX_TOKENS", d.max_tokens, int, 1),
            temperature=number("ODOS_BEDROCK_TEMPERATURE", d.temperature, float, 0.0),
            connect_timeout=number("ODOS_BEDROCK_CONNECT_TIMEOUT_SECONDS", d.connect_timeout, float, 1.0),
            read_timeout=number("ODOS_BEDROCK_READ_TIMEOUT_SECONDS", d.read_timeout, float, 1.0),
            max_attempts=number("ODOS_BEDROCK_MAX_ATTEMPTS", d.max_attempts, int, 1),
            context_tokens=number("ODOS_BEDROCK_CONTEXT_TOKENS", d.context_tokens, int, 1),
            output_retries=_at_most(number("ODOS_BEDROCK_OUTPUT_RETRIES", d.output_retries, int, 0),
                                    MAX_OUTPUT_RETRIES, "ODOS_BEDROCK_OUTPUT_RETRIES"),
        )


def _at_most(value: int, limit: int, name: str) -> int:
    if value > limit:
        raise BedrockConfigError(f"{name} must be at most {limit} (each retry is a paid model call), got {value}.")
    return value


# ── response ──────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BedrockResponse:
    text: str
    stop_reason: str  # end_turn, stop_sequence, max_tokens, ...
    input_tokens: int
    output_tokens: int
    latency_ms: int | None
    model_id: str

    @property
    def truncated(self) -> bool:
        """The answer hit the token limit and is incomplete."""
        return self.stop_reason == "max_tokens"


# ── client ────────────────────────────────────────────────────────────────────────────────────────────────────────────

_AUTH_CODES = {"AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException", "InvalidSignatureException",
               "UnauthorizedException", "InvalidClientTokenId"}
_THROTTLE_CODES = {"ThrottlingException", "ServiceQuotaExceededException", "TooManyRequestsException"}
_UNAVAILABLE_CODES = {"ServiceUnavailableException", "InternalServerException", "ModelErrorException", "ModelNotReadyException"}
_FAILED_STOPS = {"content_filtered", "guardrail_intervened"}


class BedrockClient:
    """A thin, reusable wrapper around ``bedrock-runtime`` ``converse``. Create it once and share it (boto3 clients are
    thread-safe). Pass ``client`` to use a prepared or fake boto3 client (tests); the API key is then not required."""

    def __init__(self, config: BedrockConfig | None = None, *, client: Any = None, environ: Mapping[str, str] | None = None) -> None:
        self.config = config or BedrockConfig.from_env(environ)
        self._environ = os.environ if environ is None else environ
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> Any:
        if not (self._environ.get(API_KEY_ENV) or "").strip():
            raise BedrockConfigError(
                f"{API_KEY_ENV} is not set. Create a Bedrock API key in the AWS console and put it into .env or export it "
                "(see Documentation/bedrock-rule-extraction.md); never commit it.")
        cfg = self.config
        boto_config = Config(
            region_name=cfg.region,
            connect_timeout=cfg.connect_timeout,
            read_timeout=cfg.read_timeout,
            retries={"total_max_attempts": cfg.max_attempts, "mode": "standard"},  # not "max_attempts": that counts retries, not requests
            user_agent_extra="odos",
        )
        return boto3.client(SERVICE, config=boto_config)

    def converse(self, system: str, user: str, *, max_tokens: int | None = None, temperature: float | None = None,
                 history: list[tuple[str, str]] | None = None) -> BedrockResponse:
        """One request: `history` are earlier (role, text) turns before the user message `user` (roles alternate,
        starting with "user"). Raises `BedrockError` (never a boto exception)."""
        cfg = self.config
        messages = [{"role": role, "content": [{"text": text}]} for role, text in history or []]
        request = {
            "modelId": cfg.model_id,
            "system": [{"text": system}],
            "messages": [*messages, {"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {
                "maxTokens": max_tokens or cfg.max_tokens,
                "temperature": cfg.temperature if temperature is None else temperature,
            },
        }
        try:
            raw = self.client.converse(**request)
        except BedrockError:
            raise
        except ClientError as e:
            raise self._map_client_error(e) from None
        except (ReadTimeoutError, ConnectTimeoutError) as e:
            raise BedrockTimeoutError(
                f"Bedrock did not answer in time ({type(e).__name__}) after {cfg.max_attempts} attempt(s); "
                "raise ODOS_BEDROCK_READ_TIMEOUT_SECONDS for long answers.", cause=type(e).__name__) from None
        except EndpointConnectionError as e:
            raise BedrockUnavailableError(f"Cannot connect to Bedrock in region {cfg.region}.", cause=type(e).__name__) from None
        except (BotoConnectionError, HTTPClientError) as e:
            # The connection failed or was closed before a complete answer arrived (ConnectionClosedError, SSLError,
            # ProxyConnectionError, ResponseStreamingError). botocore retries these (see max_attempts) and treats them as
            # transient, so they are "unavailable", not a request that Bedrock rejected.
            raise BedrockUnavailableError(
                f"The connection to Bedrock failed ({type(e).__name__}) after {cfg.max_attempts} attempt(s).",
                cause=type(e).__name__) from None
        except BotoCoreError as e:  # e.g. NoRegionError, ParamValidationError: the request could not even be built
            raise BedrockRequestError(self._redact(f"Bedrock request failed: {e}"), cause=type(e).__name__) from None
        response = self._parse(raw)
        log.info("bedrock converse model=%s stop=%s in=%s out=%s latency_ms=%s", response.model_id, response.stop_reason,
                 response.input_tokens, response.output_tokens, response.latency_ms)
        return response

    # -- helpers -----------------------------------------------------------------------------------------------------

    def _redact(self, message: str) -> str:
        token = (self._environ.get(API_KEY_ENV) or "").strip()
        return message.replace(token, "***") if token else message

    def _map_client_error(self, e: ClientError) -> BedrockError:
        """The typed error, carrying the AWS error code, the HTTP status and the retry count (see `diagnostics`)."""
        mapped = self._classify_client_error(e)
        meta = e.response.get("ResponseMetadata", {})
        mapped.http_status, mapped.retry_attempts = meta.get("HTTPStatusCode"), meta.get("RetryAttempts")
        return mapped

    def _classify_client_error(self, e: ClientError) -> BedrockError:
        error = e.response.get("Error", {})
        code = error.get("Code") or "Unknown"
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        message = self._redact(error.get("Message") or str(e))
        text = f"Bedrock {code}: {message}"
        if code in _AUTH_CODES or status in (401, 403):
            return BedrockAuthError(f"{text} (check {API_KEY_ENV}, the key's expiry, and that the model is enabled for it)", code=code)
        if code in _THROTTLE_CODES or (status == 429 and code not in _UNAVAILABLE_CODES):
            return BedrockThrottledError(text, code=code)
        if code == "ModelTimeoutException" or status == 408:
            return BedrockTimeoutError(text, code=code)
        if code in _UNAVAILABLE_CODES or (status or 0) >= 500:
            return BedrockUnavailableError(text, code=code)
        lowered = message.lower()
        if code == "ValidationException":
            if "too long" in lowered or ("context" in lowered and ("exceed" in lowered or "maximum" in lowered)):
                return BedrockContextLimitError(f"{text} (the input exceeds the model's context window)", code=code)
            if "inference profile" in lowered:
                return BedrockRequestError(
                    f"{text} (use an inference profile ID such as {DEFAULT_MODEL_ID} in ODOS_BEDROCK_MODEL_ID)", code=code)
            return BedrockRequestError(text, code=code)
        if code == "ResourceNotFoundException":
            return BedrockRequestError(f"{text} (check ODOS_BEDROCK_MODEL_ID and ODOS_BEDROCK_REGION)", code=code)
        return BedrockError(text, code=code)

    def _parse(self, raw: Any) -> BedrockResponse:
        try:
            blocks = raw["output"]["message"]["content"]
            stop_reason = raw["stopReason"]
            usage = raw.get("usage") or {}
            text = "".join(b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str))
        except (KeyError, TypeError, AttributeError):
            raise BedrockResponseError("Bedrock returned a response without output.message.content or stopReason.") from None
        if stop_reason in _FAILED_STOPS:
            raise BedrockResponseError(f"Bedrock stopped the answer (stopReason={stop_reason}).", code=stop_reason)
        if not text.strip():
            raise BedrockResponseError(f"Bedrock returned no text (stopReason={stop_reason}).")
        return BedrockResponse(
            text=text,
            stop_reason=str(stop_reason),
            input_tokens=int(usage.get("inputTokens") or 0),
            output_tokens=int(usage.get("outputTokens") or 0),
            latency_ms=(raw.get("metrics") or {}).get("latencyMs"),
            model_id=self.config.model_id,
        )
