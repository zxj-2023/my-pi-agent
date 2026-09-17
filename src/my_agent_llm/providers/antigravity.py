from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from ..auth.antigravity import (
    ANTIGRAVITY_USER_AGENT,
    DEFAULT_ANTIGRAVITY_ENDPOINT,
    AntigravityAuthResolver,
)
from ..config import Config
from ..models import Message, Response, StreamChunk, ToolCall
from .openai import OpenAIProvider

logger = logging.getLogger(__name__)

ANTIGRAVITY_ROUTING: dict[str, dict[str, str]] = {
    "gemini-3.8-flash": {
        "off": "gemini-3.8-flash-low",
        "minimal": "gemini-3.8-flash-low",
        "low": "gemini-3.8-flash-low",
        "medium": "gemini-3.8-flash-medium",
        "high": "gemini-3.8-flash-high",
    },
    "gemini-3.7-flash": {
        "off": "gemini-3.7-flash-low",
        "minimal": "gemini-3.7-flash-low",
        "low": "gemini-3.7-flash-low",
        "medium": "gemini-3.7-flash-medium",
        "high": "gemini-3.7-flash-high",
    },
    "gemini-3.6-flash": {
        "off": "gemini-3.6-flash-low",
        "minimal": "gemini-3.6-flash-low",
        "low": "gemini-3.6-flash-low",
        "medium": "gemini-3.6-flash-medium",
        "high": "gemini-3.6-flash-high",
    },
    "gemini-3.5-flash": {
        "off": "gemini-3.5-flash-extra-low",
        "minimal": "gemini-3.5-flash-extra-low",
        "low": "gemini-3.5-flash-extra-low",
        "medium": "gemini-3.5-flash-low",
        "high": "gemini-3-flash-agent",
    },
    "gemini-3.1-pro": {
        "off": "gemini-3.1-pro-low",
        "minimal": "gemini-3.1-pro-low",
        "low": "gemini-3.1-pro-low",
        "medium": "gemini-3.1-pro-low",
        "high": "gemini-pro-agent",
    },
    "claude-sonnet-4-6": {
        "off": "claude-sonnet-4-6",
        "minimal": "claude-sonnet-4-6",
        "low": "claude-sonnet-4-6",
        "medium": "claude-sonnet-4-6",
        "high": "claude-sonnet-4-6",
    },
    "claude-opus-4-6": {
        "off": "claude-opus-4-6-thinking",
        "minimal": "claude-opus-4-6-thinking",
        "low": "claude-opus-4-6-thinking",
        "medium": "claude-opus-4-6-thinking",
        "high": "claude-opus-4-6-thinking",
    },
    "gpt-oss-120b": {
        "off": "gpt-oss-120b-medium",
        "minimal": "gpt-oss-120b-medium",
        "low": "gpt-oss-120b-medium",
        "medium": "gpt-oss-120b-medium",
        "high": "gpt-oss-120b-medium",
    },
}

ENDPOINT_CANDIDATES = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
]


class AntigravityProvider(OpenAIProvider):
    """Google Cloud Code Assist (Antigravity) 原生 SSE 流式模型提供商适配器。"""

    def __init__(
        self,
        config: Config,
        client: Any | None = None,
        async_client: Any | None = None,
    ) -> None:
        self.auth_resolver = AntigravityAuthResolver()
        base_url = config.base_url or os.environ.get("ANTIGRAVITY_BASE_URL") or DEFAULT_ANTIGRAVITY_ENDPOINT

        # 自动解析有效 Token
        api_key = config.api_key
        self.project_id = os.environ.get("ANTIGRAVITY_PROJECT_ID", "aicode-consumers")
        if not api_key:
            try:
                creds = self.auth_resolver.get_valid_credentials()
                api_key = creds.access_token
                self.project_id = creds.project_id
            except Exception:
                api_key = "placeholder_token"  # noqa: S105

        config = config.model_copy(
            update={
                "base_url": base_url,
                "api_key": api_key,
            }
        )
        self.base_url = base_url
        self.config = config

        self._is_mock_client = client is not None or async_client is not None
        super().__init__(config, client=client, async_client=async_client)

    def _build_headers(self) -> dict[str, str]:
        token = self.config.api_key or ""
        return {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": self.project_id,
            "User-Agent": ANTIGRAVITY_USER_AGENT,
            "Content-Type": "application/json",
        }

    def _resolve_runtime_model(self, model: str, thinking_level: str | None = None) -> str:
        level = (thinking_level or "low").lower()
        if level in ("xhigh", "max"):
            level = "high"
        elif level == "minimal":
            level = "low"
        if model in ANTIGRAVITY_ROUTING:
            return ANTIGRAVITY_ROUTING[model].get(level, ANTIGRAVITY_ROUTING[model].get("low", model))
        return model

    def _convert_antigravity_messages(
        self, messages: list[Message]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append({"text": msg.content})
                continue

            if msg.role == "user":
                contents.append(
                    {
                        "role": "user",
                        "parts": [{"text": msg.content or ""}],
                    }
                )
            elif msg.role == "assistant":
                parts: list[dict[str, Any]] = []
                if msg.content:
                    parts.append({"text": msg.content})
                tool_calls = (msg.metadata or {}).get("tool_calls") or []
                for tc in tool_calls:
                    tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                    tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                    if tc_name:
                        parts.append(
                            {
                                "functionCall": {
                                    "name": tc_name,
                                    "args": (tc_args if isinstance(tc_args, dict) else {}),
                                }
                            }
                        )
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})
            elif msg.role == "tool":
                tool_name = (msg.metadata or {}).get("tool_name", "tool")
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"result": msg.content or ""},
                                }
                            }
                        ],
                    }
                )

        system_instruction = {"role": "user", "parts": system_parts} if system_parts else None
        return contents, system_instruction

    @staticmethod
    def _inline_schema_defs(schema: dict[str, Any]) -> dict[str, Any]:
        """将 Pydantic 生成的 $defs/$ref 递归内联展开，消除 Google Protobuf 解析异常。"""
        try:
            s = json.loads(json.dumps(schema))
        except Exception:
            return schema
        defs = s.pop("$defs", {}) or s.pop("definitions", {})

        def _replace(obj: Any) -> Any:
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref = str(obj["$ref"])
                    ref_key = ref.split("/")[-1]
                    if ref_key in defs:
                        resolved = _replace(defs[ref_key])
                        merged = {k: v for k, v in obj.items() if k != "$ref"}
                        if isinstance(resolved, dict):
                            return {**resolved, **merged}
                        return resolved
                return {k: _replace(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_replace(x) for x in obj]
            return obj

        return _replace(s)

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        declarations: list[dict[str, Any]] = []
        for t in tools:
            fn = t.get("function", t)
            name = fn.get("name", "")
            if not name:
                continue
            raw_params = fn.get("parameters") or {"type": "object", "properties": {}}
            clean_params = self._inline_schema_defs(raw_params)
            decl: dict[str, Any] = {
                "name": name,
                "description": fn.get("description", ""),
                "parametersJsonSchema": clean_params,
            }
            declarations.append(decl)

        if declarations:
            return [{"functionDeclarations": declarations}]
        return None

    @property
    def _is_mock(self) -> bool:
        if self._is_mock_client:
            return True
        c = getattr(self, "client", None)
        if c is not None and type(c).__module__ != "openai":
            return True
        ac = getattr(self, "async_client", None)
        if ac is not None and type(ac).__module__ != "openai":
            return True
        return False

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        if self._is_mock:
            return super().chat(messages, model=model, tools=tools, **kwargs)
        return asyncio.run(self.achat(messages, model=model, tools=tools, **kwargs))

    def stream(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Iterator[StreamChunk]:
        if self._is_mock:
            for c in super().stream(messages, model=model, tools=tools, **kwargs):
                yield c
            return

        loop = asyncio.new_event_loop()
        try:
            gen = self.achat_stream(messages, model=model, tools=tools, **kwargs)
            while True:
                try:
                    chunk = loop.run_until_complete(gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    async def achat(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Response:
        if self._is_mock:
            return await super().achat(messages, model=model, tools=tools, **kwargs)

        full_content: list[str] = []
        reasoning_list: list[str] = []
        tool_calls: list[ToolCall] = []
        usage: dict[str, Any] | None = None
        finish_reason: str = "stop"

        async for chunk in self.achat_stream(messages, model=model, tools=tools, **kwargs):
            if chunk.content:
                full_content.append(chunk.content)
            if chunk.metadata and chunk.metadata.get("reasoning_content"):
                reasoning_list.append(chunk.metadata["reasoning_content"])
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason

        return Response(
            content="".join(full_content),
            model=model,
            tool_calls=tool_calls if tool_calls else None,
            reasoning_content="".join(reasoning_list) or None,
            usage=usage,
            finish_reason=finish_reason,
        )

    async def achat_stream(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        if self._is_mock:
            async for chunk in super().achat_stream(messages, model=model, tools=tools, **kwargs):
                yield chunk
            return

        # 1. 解析最新凭据
        access_token = self.config.api_key
        project_id = self.project_id
        try:
            creds = self.auth_resolver.get_valid_credentials()
            access_token = creds.access_token
            project_id = creds.project_id or project_id
        except Exception as exc:
            logger.debug("Antigravity 凭据解析失败，尝试环境变量或已存配置: %s", exc)

        # 2. 映射运行时模型 ID
        runtime_model = self._resolve_runtime_model(model, kwargs.get("thinking_level"))

        # 3. 构造请求体
        contents, system_instruction = self._convert_antigravity_messages(messages)
        request_obj: dict[str, Any] = {"contents": contents}
        if system_instruction:
            request_obj["systemInstruction"] = system_instruction
        tool_decl = self._convert_tools(tools)
        if tool_decl:
            request_obj["tools"] = tool_decl

        payload = {
            "project": project_id,
            "model": runtime_model,
            "request": request_obj,
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": ANTIGRAVITY_USER_AGENT,
        }

        # 4. 遍历多候选端点容灾发起 SSE 流式调用 (对标 pi-antigravity)
        endpoints = (
            [self.base_url]
            if (self.base_url and self.base_url != DEFAULT_ANTIGRAVITY_ENDPOINT)
            else ENDPOINT_CANDIDATES
        )

        timeout = kwargs.get("timeout", self.config.timeout or 60.0)
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            resp = None
            for ep in endpoints:
                url = f"{ep}/v1internal:streamGenerateContent?alt=sse"
                try:
                    r = await http_client.post(url, headers=headers, json=payload)
                    if r.status_code == 200:
                        resp = r
                        break
                    elif r.status_code != 429:
                        resp = r
                        break
                except Exception:
                    continue

            if resp is None or resp.status_code != 200:
                err_text = resp.text[:300] if resp else "Connection error"
                raise RuntimeError(f"Antigravity request failed ({resp.status_code if resp else 'error'}): {err_text}")

            # 5. 解析 SSE 响应并实时产出 StreamChunk
            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0
            thought_tokens = 0
            total_tokens = 0
            finish_reason = None
            tool_calls: list[ToolCall] = []

            for line in resp.text.splitlines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                response_data = data.get("response", {})
                usage_meta = response_data.get("usageMetadata")
                if usage_meta:
                    prompt_tokens = usage_meta.get("promptTokenCount", 0)
                    cached_tokens = usage_meta.get("cachedContentTokenCount", 0)
                    thought_tokens = usage_meta.get("thoughtsTokenCount", 0)
                    completion_tokens = usage_meta.get("candidatesTokenCount", 0) + thought_tokens
                    total_tokens = usage_meta.get("totalTokenCount", 0)

                candidates = response_data.get("candidates", [])
                for cand in candidates:
                    if cand.get("finishReason"):
                        finish_reason = cand["finishReason"]
                    parts = cand.get("content", {}).get("parts", [])
                    for p in parts:
                        if p.get("thought"):
                            yield StreamChunk(
                                content="",
                                metadata={"reasoning_content": p.get("text", "")},
                            )
                        elif "text" in p:
                            yield StreamChunk(content=p["text"])
                        elif "functionCall" in p:
                            fn = p["functionCall"]
                            call_id = f"call_{uuid.uuid4().hex[:8]}"
                            tc = ToolCall(
                                id=call_id,
                                name=fn.get("name", ""),
                                args=fn.get("args", {}),
                            )
                            tool_calls.append(tc)
                            yield StreamChunk(content="", tool_calls=[tc])

            # 最终块携带完整 Usage
            usage_dict: dict[str, Any] = {
                "prompt_tokens": max(0, prompt_tokens - cached_tokens),
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
            if cached_tokens > 0:
                usage_dict["cache_read_tokens"] = cached_tokens
            if thought_tokens > 0:
                usage_dict["reasoning_tokens"] = thought_tokens
            yield StreamChunk(
                content="",
                finish_reason=finish_reason or "stop",
                usage=usage_dict,
                tool_calls=tool_calls if tool_calls else None,
            )
