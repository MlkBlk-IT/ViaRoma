"""
Module: src/proxy/sse_converter.py
Role: Parse/normalize native provider SSE streams -> ChatChunk (OpenAI format).
Supports: OpenAI, Claude, Gemini, ChatGPT, Grok, Perplexity, Poe, HuggingChat,
          You.com, MetaAI, Copilot, Kimi, GLM, DeepSeek, Qwen, Lepton.
"""
from __future__ import annotations

import json
import re
import logging
from typing import AsyncGenerator, Dict, Any, Optional, Callable

from src.schemas import ChatChunk, ChatChoice, DeltaMessage

logger = logging.getLogger(__name__)


async def iter_sse_lines(response) -> AsyncGenerator[Optional[str], None]:
    # curl_cffi async: aiter_lines / aiter_content (check ASYNC first)
    if hasattr(response, "aiter_lines"):
        async for line in response.aiter_lines():
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", "ignore")
            if line:
                yield line
    elif hasattr(response, "aiter_content"):
        buf = ""
        async for raw in response.aiter_content():
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "ignore")
            buf += raw
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if line.strip():
                    yield line
    elif hasattr(response, "aiter_lines"):
        async for line in response.aiter_lines():
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", "ignore")
            if line:
                yield line
    else:
        content = getattr(response, "content", None) or getattr(response, "body", None)
        if content is not None:
            if isinstance(content, (bytes, bytearray)):
                content = content.decode("utf-8", "ignore")
            for line in str(content).splitlines():
                if line:
                    yield line


def strip_data_prefix(line: str) -> Optional[str]:
    if not line:
        return None
    if line.startswith("data:"):
        return line[5:].strip()
    return None


def _delta(content=None, role=None):
    return ChatChunk(choices=[ChatChoice(delta=DeltaMessage(role=role, content=content))])

def _stop():
    return ChatChunk(choices=[ChatChoice(delta=DeltaMessage(), finish_reason="stop")])


async def parse_openai_sse(response):
    """OpenAI-compatible SSE: used by Qwen, DeepSeek, Kimi, GLM, Lepton, Grok, Perplexity."""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = parsed.get("choices") or []
        if choices:
            d = choices[0].get("delta") or choices[0].get("message") or {}
            content = d.get("content")
            if content:
                yield _delta(content=content, role=d.get("role"))
        if choices and choices[0].get("finish_reason"):
            yield _stop()
            return


async def parse_claude_sse(response):
    """Claude web: {"completion": "text", "stop_reason": null}"""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        text = parsed.get("completion") or ""
        if text:
            yield _delta(content=text)
        if parsed.get("stop_reason"):
            yield _stop()


async def parse_gemini_sse(response):
    """Gemini: {"candidates":[{"content":{"parts":[{"text":"..."}]}}]}"""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        candidates = parsed.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                text = part.get("text") or ""
                if text:
                    yield _delta(content=text)
        if candidates and candidates[0].get("finishReason"):
            yield _stop()


async def parse_chatgpt_sse(response):
    """ChatGPT web: event-stream with 'data: {"v": {"message": {"content": {"parts": ["text"]}}}}'"""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        # ChatGPT SSE: {"v": {"message": {"content": {"parts": ["text"]}}}}
        v = parsed.get("v") or parsed
        msg = v.get("message") or {}
        parts = (msg.get("content") or {}).get("parts") or []
        for part in parts:
            if isinstance(part, str) and part:
                yield _delta(content=part)
        if msg.get("end_turn"):
            yield _stop()


async def parse_copilot_sse(response):
    """Copilot/Bing: 'data: {"messages": [{"text": "...", "author": "bot"}]}'"""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        msgs = parsed.get("messages") or []
        for m in msgs:
            if m.get("author") in ("bot", "assistant"):
                text = m.get("text") or ""
                if text:
                    yield _delta(content=text)
        if parsed.get("stop"):
            yield _stop()


async def parse_poe_sse(response):
    """Poe GraphQL SSE: 'data: {"data": {"messageAdded": {"text": "..."}}}'"""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        data = parsed.get("data") or {}
        msg = data.get("messageAdded") or data.get("message") or {}
        text = msg.get("text") or msg.get("content") or ""
        if text:
            yield _delta(content=text)
        if msg.get("state") == "complete":
            yield _stop()


async def parse_huggingchat_sse(response):
    """HuggingChat: 'data: {"generated_text": "..."}' or OpenAI format."""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        # Try OpenAI format first
        choices = parsed.get("choices") or []
        if choices:
            d = choices[0].get("delta") or {}
            content = d.get("content")
            if content:
                yield _delta(content=content)
            if choices[0].get("finish_reason"):
                yield _stop()
            continue
        # Fallback: generated_text
        text = parsed.get("generated_text") or parsed.get("token", {}).get("text", "")
        if text:
            yield _delta(content=text)


async def parse_you_sse(response):
    """You.com: custom JSON streaming."""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        # You.com returns text in various fields
        text = parsed.get("text") or parsed.get("answer") or parsed.get("snippet") or ""
        if text:
            yield _delta(content=text)
        if parsed.get("done"):
            yield _stop()


async def parse_metaai_sse(response):
    """Meta AI GraphQL SSE."""
    async for line in iter_sse_lines(response):
        payload = strip_data_prefix(line)
        if payload is None:
            continue
        if payload == "[DONE]":
            yield _stop()
            return
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        # Meta AI: nested GraphQL response
        data = parsed.get("data") or parsed
        msg = data.get("message") or data.get("externalConversation") or {}
        text = msg.get("text") or msg.get("content") or ""
        if text:
            yield _delta(content=text)
        if msg.get("streaming") is False:
            yield _stop()


PARSERS: Dict[str, Callable] = {
    "openai": parse_openai_sse,
    "claude": parse_claude_sse,
    "gemini": parse_gemini_sse,
    "chatgpt": parse_chatgpt_sse,
    "copilot": parse_copilot_sse,
    "poe": parse_poe_sse,
    "huggingchat": parse_huggingchat_sse,
    "you": parse_you_sse,
    "metaai": parse_metaai_sse,
}

# OpenAI-compatible providers reuse parse_openai_sse
for _k in ("qwen", "deepseek", "kimi", "glm", "grok", "perplexity", "lepton"):
    PARSERS[_k] = parse_openai_sse


def get_parser(kind: str) -> Callable:
    if kind not in PARSERS:
        # Default to openai parser for unknown formats
        logger.warning("Unknown SSE parser %s, defaulting to openai", kind)
        return parse_openai_sse
    return PARSERS[kind]


def chunk_to_sse(chunk: ChatChunk) -> str:
    return "data: " + chunk.model_dump_json() + "\n\n"

def done_sse() -> str:
    return "data: [DONE]\n\n"
