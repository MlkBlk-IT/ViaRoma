"""
Module: src/proxy/proxy_engine.py
Role: OpenAI <-> web provider translation layer.
Real implementations for 15 web chat adapters + OpenAI passthrough.
Each adapter builds provider-specific payloads and streams via curl_cffi with TLS spoofing.
SSE parsing delegated to src.proxy.sse_converter.
"""
from __future__ import annotations

import json
import uuid
import time
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional

from src.schemas import ChatCompletionRequest, ChatChunk
from src.proxy.sse_converter import get_parser
from src.proxy.anti_waf_harvester import TLSSpoofer

logger = logging.getLogger(__name__)

# Credential fields that are NOT cookies: they should never
# leave in the Cookie header. "cookie" contains a STRING of cookies
# (sessionKey=..; __session=..) which is parsed upstream by providers.py.
NON_COOKIE_FIELDS = {
    "cookie", "org_id", "access_token", "device_id", "token", "api_key",
    "auth_token", "username", "password", "email",
}


class ProviderError(Exception):
    pass


class ProviderAdapter(ABC):
    def __init__(self, session_id, cookies=None, creds=None, user_agent="", proxy=None,
                 tls_profile="chrome120", locale=""):
        self.session_id = session_id
        # cookies = jar (name -> value) -> Cookie header.
        # creds = all (jar + tokens + meta) -> Authorization / URL / device id.
        # A credential is NEVER a cookie: "cookie" is a string of cookies
        # (parsed upstream), the tokens go to the Authorization header.
        self.cookies = cookies or {}
        self.creds = creds if creds is not None else self.cookies
        self.user_agent = user_agent
        self.locale = locale
        self.proxy = proxy
        self.tls_profile = tls_profile
        self._spoofer = TLSSpoofer(profile=tls_profile, proxy=proxy)

    @property
    @abstractmethod
    def provider_name(self): pass

    @property
    @abstractmethod
    def base_url(self): pass

    @property
    def sse_kind(self): return "openai"

    @property
    def chat_path(self): return "/api/chat"

    @abstractmethod
    def build_request_payload(self, request): pass

    def _extra_headers(self): return None

    def _build_headers(self, extra=None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Accept-Language": (self.locale + ",en;q=0.9") if self.locale else "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if self.cookies:
            jar = {k: v for k, v in self.cookies.items()
                   if k not in NON_COOKIE_FIELDS and v not in (None, "")}
            if jar:
                headers["Cookie"] = "; ".join(k + "=" + v for k, v in jar.items())
        if extra:
            headers.update(extra)
        return headers

    async def get_client(self):
        return self._spoofer.get_session()

    async def stream_chat(self, request):
        client = await self.get_client()
        payload = self.build_request_payload(request)
        url = self.base_url + self.chat_path
        headers = self._build_headers(self._extra_headers())
        parser = get_parser(self.sse_kind)
        try:
            if self._spoofer.is_stub:
                async with client.post(url, json=payload, headers=headers, proxy=self.proxy) as resp:
                    if resp.status in (401, 403):
                        raise PermissionError(self.provider_name + " auth expired (" + str(resp.status) + ")")
                    if resp.status == 429:
                        raise ResourceWarning(self.provider_name + " rate-limit (429)")
                    async for chunk in parser(resp):
                        yield chunk
            else:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code in (401, 403):
                        raise PermissionError(self.provider_name + " auth expired (" + str(resp.status_code) + ")")
                    if resp.status_code == 429:
                        raise ResourceWarning(self.provider_name + " rate-limit (429)")
                    async for chunk in parser(resp):
                        yield chunk
        except (PermissionError, ResourceWarning):
            raise
        except Exception as e:
            raise ProviderError(self.provider_name + " error: " + str(e)) from e

    async def close(self):
        await self._spoofer.close()


def _last_user_msg(request):
    msg = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    return msg if isinstance(msg, str) else str(msg)

def _msgs(request):
    return [{"role": m.role, "content": m.content if isinstance(m.content, str) else str(m.content)} for m in request.messages]


class ClaudeWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "ClaudeWeb"
    @property
    def base_url(self): return "https://claude.ai"
    @property
    def sse_kind(self): return "claude"
    @property
    def chat_path(self):
        org_id = self.creds.get("org_id", "") or self.cookies.get("org_id", "") or "unknown"
        return "/api/organizations/" + org_id + "/chat_conversations"
    def _extra_headers(self):
        return {"Anthropic-Client-Version": "2024-10-22"}
    def build_request_payload(self, request):
        return {
            "prompt": _last_user_msg(request),
            "model": request.model or "claude-3-5-sonnet-20241022",
            "max_tokens_to_sample": request.max_tokens or 4096,
            "temperature": request.temperature,
            "stream": True,
            "metadata": {"conversation_id": str(uuid.uuid4())},
        }

class GeminiWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "GeminiWeb"
    @property
    def base_url(self): return "https://gemini.google.com"
    @property
    def sse_kind(self): return "gemini"
    @property
    def chat_path(self): return "/_/BardChatUi/data/assistant.lamda.bard.BardFrontendService/StreamGenerate"
    def _extra_headers(self):
        # The auth_token is required by PROVIDER_META but was never sent:
        # without it Gemini responds 401 regardless of the credential provided.
        h = {"X-Same-Domain": "1"}
        token = self.creds.get("auth_token", "") or self.cookies.get("auth_token", "")
        if token:
            h["Authorization"] = "Bearer " + token
        return h
    def build_request_payload(self, request):
        contents = []
        for m in request.messages:
            role = "user" if m.role == "user" else "model"
            content = m.content if isinstance(m.content, str) else str(m.content)
            contents.append({"role": role, "parts": [{"text": content}]})
        return {"contents": contents, "generationConfig": {"temperature": request.temperature, "maxOutputTokens": request.max_tokens or 4096}}

class ChatGPTWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "ChatGPTWeb"
    @property
    def base_url(self): return "https://chatgpt.com"
    @property
    def sse_kind(self): return "chatgpt"
    @property
    def chat_path(self): return "/backend-api/conversation"
    def _extra_headers(self):
        h = {"Authorization": "Bearer " + (self.creds.get("access_token", "")
                                           or self.cookies.get("access_token", ""))}
        # device_id is required by PROVIDER_META but was never sent.
        device_id = self.creds.get("device_id", "") or self.cookies.get("device_id", "")
        if device_id:
            h["oai-device-id"] = device_id
        return h
    def build_request_payload(self, request):
        msgs = []
        for m in request.messages:
            content = m.content if isinstance(m.content, str) else str(m.content)
            msgs.append({"id": str(uuid.uuid4()), "role": m.role, "content": {"content_type": "text", "parts": [content]}})
        return {"action": "next", "messages": msgs, "model": request.model or "gpt-4o", "parent_message_id": str(uuid.uuid4()), "conversation_id": None}

class QwenWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "QwenWeb"
    @property
    def base_url(self): return "https://chat.qwen.ai"
    @property
    def chat_path(self): return "/api/chat/completions"
    def _extra_headers(self): return {"Authorization": "Bearer " + self.creds.get("token", "")}
    def build_request_payload(self, request):
        return {"model": request.model or "qwen-max", "messages": _msgs(request), "stream": True, "temperature": request.temperature, "max_tokens": request.max_tokens or 4096}

class CopilotWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "CopilotWeb"
    @property
    def base_url(self): return "https://copilot.microsoft.com"
    @property
    def sse_kind(self): return "copilot"
    @property
    def chat_path(self): return "/c/bing/chat"
    def _extra_headers(self): return {"X-Edge-Shopping-Enabled": "false"}
    def build_request_payload(self, request):
        msgs = [{"text": m.content if isinstance(m.content, str) else str(m.content), "author": m.role} for m in request.messages]
        return {"conversationSignature": "", "messages": msgs, "tone": "Balanced"}

class GrokWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "GrokWeb"
    @property
    def base_url(self): return "https://grok.com"
    @property
    def chat_path(self): return "/rest/app-chat/conversations/new"
    def _extra_headers(self): return {"X-Xai-Client": "web"}
    def build_request_payload(self, request):
        return {"messages": _msgs(request), "model": request.model or "grok-3", "stream": True, "temperature": request.temperature}

class PerplexityWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "PerplexityWeb"
    @property
    def base_url(self): return "https://www.perplexity.ai"
    @property
    def chat_path(self): return "/rest/chat/v1"
    def _extra_headers(self): return {"X-Client-Version": "web"}
    def build_request_payload(self, request):
        return {"messages": _msgs(request), "model": request.model or "sonar-pro", "stream": True, "temperature": request.temperature}

class DeepSeekWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "DeepSeekWeb"
    @property
    def base_url(self): return "https://chat.deepseek.com"
    @property
    def chat_path(self): return "/api/v0/chat/completions"
    def _extra_headers(self): return {"Authorization": "Bearer " + self.creds.get("token", "")}
    def build_request_payload(self, request):
        return {"model": request.model or "deepseek-v3", "messages": _msgs(request), "stream": True, "temperature": request.temperature, "max_tokens": request.max_tokens or 4096}

class KimiWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "KimiWeb"
    @property
    def base_url(self): return "https://kimi.moonshot.cn"
    @property
    def chat_path(self): return "/api/chat/completions"
    def _extra_headers(self): return {"Authorization": "Bearer " + self.creds.get("token", "")}
    def build_request_payload(self, request):
        return {"model": request.model or "moonshot-v1-128k", "messages": _msgs(request), "stream": True, "temperature": request.temperature}

class GLMWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "GLMWeb"
    @property
    def base_url(self): return "https://chatglm.cn"
    @property
    def chat_path(self): return "/chatglm/backend-api/assistant/stream"
    def _extra_headers(self): return {"Authorization": "Bearer " + self.creds.get("token", "")}
    def build_request_payload(self, request):
        return {"model": request.model or "glm-4-plus", "messages": _msgs(request), "stream": True, "temperature": request.temperature, "max_tokens": request.max_tokens or 4096}

class MetaAIWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "MetaAIWeb"
    @property
    def base_url(self): return "https://www.meta.ai"
    @property
    def sse_kind(self): return "metaai"
    @property
    def chat_path(self): return "/api/graphql"
    def _extra_headers(self): return {"Content-Type": "application/json"}
    def build_request_payload(self, request):
        user_text = "\n".join(m.content if isinstance(m.content, str) else str(m.content) for m in request.messages if m.role == "user")
        return {"0": {"json": {"message": user_text, "stream": True}}}

class PoeWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "PoeWeb"
    @property
    def base_url(self): return "https://poe.com"
    @property
    def sse_kind(self): return "poe"
    @property
    def chat_path(self): return "/api/gql_POST"
    def _extra_headers(self): return {"Poe-Form-Name": "MessageSubmitForm"}
    def build_request_payload(self, request):
        return {"queryName": "MessageSubmitForm", "variables": {"bot": "Claude-Sonnet-3.5", "messages": _msgs(request), "stream": True}}

class HuggingChatWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "HuggingChatWeb"
    @property
    def base_url(self): return "https://huggingface.co"
    @property
    def sse_kind(self): return "huggingchat"
    @property
    def chat_path(self): return "/chat/conversation"
    def _extra_headers(self): return {"X-Inference-Stream": "1"}
    def build_request_payload(self, request):
        return {"model": request.model or "meta-llama/Meta-Llama-3.1-70B-Instruct", "messages": _msgs(request), "stream": True, "temperature": request.temperature, "max_tokens": request.max_tokens or 4096}

class YouWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "YouWeb"
    @property
    def base_url(self): return "https://you.com"
    @property
    def sse_kind(self): return "you"
    @property
    def chat_path(self): return "/api/streamingSearch"
    def build_request_payload(self, request):
        return {"q": _last_user_msg(request), "stream": True}

class LeptonWebAdapter(ProviderAdapter):
    @property
    def provider_name(self): return "LeptonWeb"
    @property
    def base_url(self): return "https://www.lepton.ai"
    @property
    def chat_path(self): return "/api/v1/chat/completions"
    def _extra_headers(self): return {"Authorization": "Bearer " + self.creds.get("api_key", "")}
    def build_request_payload(self, request):
        return {"model": request.model or "gpt-4o", "messages": _msgs(request), "stream": True, "temperature": request.temperature, "max_tokens": request.max_tokens or 4096}

class OpenAIPassthroughAdapter(ProviderAdapter):
    def __init__(self, *args, endpoint="", **kwargs):
        super().__init__(*args, **kwargs)
        self.endpoint = endpoint
    @property
    def provider_name(self): return "OpenAIPassthrough"
    @property
    def base_url(self):
        return self.endpoint.rsplit("/chat/completions", 1)[0] if "/chat/completions" in self.endpoint else self.endpoint
    @property
    def chat_path(self): return "/chat/completions"
    def build_request_payload(self, request):
        payload = {"model": request.model, "messages": [{"role": m.role, "content": m.content} for m in request.messages], "stream": True, "temperature": request.temperature}
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        return payload


class OfficialAPIAdapter(ProviderAdapter):
    """Official API account using an OpenAI-compatible chat endpoint.

    The endpoint and key are supplied through the local credential reference;
    the key is sent only as an Authorization header and never logged.
    """
    @property
    def provider_name(self): return self.creds.get("api_provider", "Official API")
    @property
    def base_url(self):
        endpoint = (self.creds.get("endpoint") or "").rstrip("/")
        return endpoint.rsplit("/chat/completions", 1)[0]
    @property
    def chat_path(self): return "/chat/completions"
    def _extra_headers(self):
        key = self.creds.get("api_key", "")
        return {"Authorization": "Bearer " + key} if key else {}
    def build_request_payload(self, request):
        payload = {
            "model": request.model or self.creds.get("model", "default"),
            "messages": _msgs(request),
            "stream": True,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        return payload

ADAPTER_REGISTRY = {
    "claude_web": ClaudeWebAdapter,
    "gemini_web": GeminiWebAdapter,
    "chatgpt_web": ChatGPTWebAdapter,
    "qwen_web": QwenWebAdapter,
    "copilot_web": CopilotWebAdapter,
    "grok_web": GrokWebAdapter,
    "perplexity_web": PerplexityWebAdapter,
    "deepseek_web": DeepSeekWebAdapter,
    "kimi_web": KimiWebAdapter,
    "glm_web": GLMWebAdapter,
    "metaai_web": MetaAIWebAdapter,
    "poe_web": PoeWebAdapter,
    "huggingchat_web": HuggingChatWebAdapter,
    "you_web": YouWebAdapter,
    "lepton_web": LeptonWebAdapter,
    "openai_passthrough": OpenAIPassthroughAdapter,
    "official_api": OfficialAPIAdapter,
}

PROVIDER_META = {
    "claude_web":       {"label": "Claude (web)",      "login_url": "https://claude.ai/login",           "credentials": ["cookie", "org_id"]},
    "gemini_web":       {"label": "Gemini (web)",      "login_url": "https://gemini.google.com",        "credentials": ["auth_token"]},
    "chatgpt_web":      {"label": "ChatGPT (web)",     "login_url": "https://chatgpt.com",               "credentials": ["access_token", "device_id"]},
    "qwen_web":         {"label": "Qwen (web)",        "login_url": "https://chat.qwen.ai",              "credentials": ["token"]},
    "copilot_web":      {"label": "Copilot (web)",    "login_url": "https://copilot.microsoft.com",     "credentials": ["cookie"]},
    "grok_web":         {"label": "Grok (web)",        "login_url": "https://grok.com",                  "credentials": ["cookie"]},
    "perplexity_web":   {"label": "Perplexity (web)", "login_url": "https://www.perplexity.ai",         "credentials": ["cookie"]},
    "deepseek_web":     {"label": "DeepSeek (web)",   "login_url": "https://chat.deepseek.com",         "credentials": ["token"]},
    "kimi_web":         {"label": "Kimi (web)",        "login_url": "https://kimi.moonshot.cn",          "credentials": ["token"]},
    "glm_web":          {"label": "GLM (web)",         "login_url": "https://chatglm.cn",               "credentials": ["token"]},
    "metaai_web":       {"label": "Meta AI (web)",    "login_url": "https://www.meta.ai",               "credentials": ["cookie"]},
    "poe_web":          {"label": "Poe (web)",         "login_url": "https://poe.com",                   "credentials": ["cookie"]},
    "huggingchat_web":  {"label": "HuggingChat (web)","login_url": "https://huggingface.co/chat",      "credentials": ["cookie"]},
    "you_web":          {"label": "You.com (web)",    "login_url": "https://you.com",                   "credentials": ["cookie"]},
    "lepton_web":       {"label": "Lepton (web)",     "login_url": "https://www.lepton.ai",             "credentials": ["api_key"]},
    "official_api":     {"label": "Official API",      "login_url": "",                                  "credentials": ["api_key", "endpoint", "api_provider"], "transport": "api"},
}

def get_adapter(provider, session_id, cookies=None, creds=None, user_agent="", proxy=None,
                tls_profile="chrome120", locale=""):
    if provider not in ADAPTER_REGISTRY:
        raise ValueError("Provider not supported: " + provider + ". Available: " + str(list(ADAPTER_REGISTRY.keys())))
    return ADAPTER_REGISTRY[provider](
        session_id=session_id, cookies=cookies, creds=creds, user_agent=user_agent,
        proxy=proxy, tls_profile=tls_profile, locale=locale,
    )

class ProxyLayer:
    def __init__(self, default_proxy=None, default_tls_profile="chrome120"):
        self.default_proxy = default_proxy
        self.default_tls_profile = default_tls_profile
        self._active_adapters = {}
    async def execute(self, request, provider, session_id, cookies=None, user_agent=""):
        adapter = get_adapter(provider=provider, session_id=session_id, cookies=cookies, user_agent=user_agent, proxy=self.default_proxy, tls_profile=self.default_tls_profile)
        key = provider + ":" + session_id
        self._active_adapters[key] = adapter
        try:
            async for chunk in adapter.stream_chat(request):
                yield chunk
        finally:
            await adapter.close()
            self._active_adapters.pop(key, None)
    async def close_all(self):
        for adapter in list(self._active_adapters.values()):
            await adapter.close()
        self._active_adapters.clear()
