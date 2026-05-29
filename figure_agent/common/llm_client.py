from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LLMClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    enabled: bool
    api_key: str | None
    base_url: str | None
    model: str
    timeout: float
    temperature: float

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            provider=os.getenv("FIGURE_AGENT_LLM_PROVIDER", "openai").lower(),
            enabled=os.getenv("FIGURE_AGENT_LLM_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
            api_key=os.getenv("FIGURE_AGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
            base_url=os.getenv("FIGURE_AGENT_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL"),
            model=os.getenv("FIGURE_AGENT_LLM_MODEL") or os.getenv("OPENAI_MODEL") or os.getenv("ANTHROPIC_MODEL") or "gpt-5.4",
            timeout=float(os.getenv("FIGURE_AGENT_LLM_TIMEOUT", "60")),
            temperature=float(os.getenv("FIGURE_AGENT_LLM_TEMPERATURE", "0")),
        )


class OpenAICompatibleLLMClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()
        self._client: Any | None = None

    @property
    def available(self) -> bool:
        return bool(self.config.enabled and self.config.api_key and self.config.base_url)

    def json_completion(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.available:
            return None
        if self.config.provider == "openai":
            return self._openai_json_completion(system_prompt, user_payload)
        if self.config.provider == "anthropic":
            return self._anthropic_json_completion(system_prompt, user_payload)
        raise LLMClientError(f"unsupported LLM provider: {self.config.provider}")

    def _openai_json_completion(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        kwargs = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ],
            "timeout": self.config.timeout,
            "response_format": {"type": "json_object"},
        }
        try:
            client = self._get_openai_client()
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:  # pragma: no cover - exercised in integration environments
            if "openai package is not installed" in str(exc):
                return self._openai_json_completion_http(kwargs)
            if "response_format" not in str(exc):
                raise LLMClientError(str(exc)) from exc
            kwargs.pop("response_format", None)
            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as retry_exc:
                raise LLMClientError(str(retry_exc)) from retry_exc
        content = response.choices[0].message.content or ""
        return extract_json_object(content)

    def _openai_json_completion_http(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.base_url or not self.config.api_key:
            raise LLMClientError("OpenAI-compatible base_url and api_key are required")
        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if payload.get("response_format") and "response_format" in detail:
                retry_payload = dict(payload)
                retry_payload.pop("response_format", None)
                return self._openai_json_completion_http(retry_payload)
            raise LLMClientError(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise LLMClientError(str(exc)) from exc

        try:
            content = response_payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("OpenAI-compatible response missing choices[0].message.content") from exc
        return extract_json_object(content)

    def _anthropic_json_completion(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        client = self._get_anthropic_client()
        try:
            response = client.messages.create(
                model=self.config.model,
                max_tokens=int(os.getenv("FIGURE_AGENT_LLM_MAX_TOKENS", "4096")),
                temperature=self.config.temperature,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
                }],
                timeout=self.config.timeout,
            )
        except Exception as exc:  # pragma: no cover - exercised in integration environments
            raise LLMClientError(str(exc)) from exc
        content = ""
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                content += getattr(block, "text", "")
        return extract_json_object(content)

    def _get_openai_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise LLMClientError("openai package is not installed") from exc
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )
        return self._client

    def _get_anthropic_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from anthropic import Anthropic
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise LLMClientError("anthropic package is not installed") from exc
        kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = Anthropic(**kwargs)
        return self._client


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMClientError("LLM response did not contain a JSON object")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise LLMClientError("LLM JSON response is not an object")
    return payload


def schema_guard_prompt(schema_name: str, task: str) -> str:
    schema = _load_schema_for_prompt(schema_name)
    required = schema.get("required", [])
    properties = sorted((schema.get("properties") or {}).keys())
    return (
        "You are a strict FigureAgent component. "
        f"Task: {task}. "
        f"Return only one JSON object that conforms exactly to {schema_name}. "
        "Do not include markdown, comments, prose, wrappers, explanations, or additional top-level keys. "
        "Do not add keys outside the schema. Do not add new claims, unbound evidence, metrics, methods, or datasets. "
        f"Required top-level keys: {', '.join(required)}. "
        f"Allowed top-level keys: {', '.join(properties)}. "
        "Exact JSON Schema follows:\n"
        f"{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
    )


def _load_schema_for_prompt(schema_name: str) -> dict[str, Any]:
    schema_dir = Path(__file__).resolve().parents[1] / "schemas"
    with (schema_dir / schema_name).open("r", encoding="utf-8") as handle:
        return json.load(handle)
