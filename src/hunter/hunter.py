
"""
Module: src/hunter/hunter.py
Role: Standalone scraper of free frontier models.
Fusion: workers/free_hunter.py + src/hunter/hunter.py (Roma).
  - preserve scan_openrouter_free() and run_discovery_loop(interval_seconds) from Roma
  - adds: persistent catalog, FRONTIER tier filter, on_discovery callback
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

import aiohttp

# ── GGUF: read quantization level in file name ──────
_QUANT_RE = re.compile(r"^(IQ\d|Q\d|BF\d|F\d|FP\d|EXL\d|TQ\d|F16|F32)")


def _gguf_quant(filename: str) -> str:
    """'Qwen2.5-7B-Instruct-Q4_K_M.gguf' -> 'Q4_K_M'.

    The actual file name is the only source of truth for the level of
    quantification: we deduce nothing, we read.
    """
    stem = filename[:-5] if filename.lower().endswith(".gguf") else filename
    for part in reversed(stem.split("-")):
        if _QUANT_RE.match(part.upper()):
            return part
    return "?"



def _log(*args, **kwargs):
    """Logs on stderr: stdout is reserved for the MCP protocol (stdio transport)."""
    kwargs.setdefault("file", sys.stderr)
    import builtins
    builtins.print(*args, **kwargs)


class ModelTier(Enum):
    FRONTIER = "frontier"
    LARGE = "large"
    MEDIUM = "medium"
    SMALL = "small"


@dataclass
class FreeModel:
    model_id: str
    provider: str
    tier: ModelTier
    # REAL context window. None = the source did not publish it.
    # We NEVER invent a value (it was 32768 written all over: a
    # lie repeated on 2000 models).
    context_window: Optional[int] = None
    discovered_at: float = field(default_factory=time.time)
    last_verified: float = field(default_factory=time.time)
    is_active: bool = True
    metadata: Dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["tier"] = self.tier.value
        return d

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["tier"] = ModelTier(data["tier"])
        # The old catalogs had a factory number 32768: we are removing it.
        if data.get("context_window") == 32768 and not (data.get("metadata") or {}).get("ctx_source"):
            data["context_window"] = None
        return cls(**data)


class FreeHunter:
    """Free standalone template scanner.
    - Interroge sources connues (OpenRouter, HuggingFace)
    - Filtre tier FRONTIER uniquement (exclut 7B/8B/mini/quantized)
    - Persists the catalog on disk
    - Callback on_discovery to notify CircuitBreaker/ProxyLayer
    """

    SOURCES = {
        # ── Free API aggregators ──
        "openrouter": "https://openrouter.ai/api/v1/models",
        "huggingface": "https://huggingface.co/api/models?filter=text-generation&sort=downloads",
        # ── HuggingFace: GGUF (real ctx + quant files), live releases ──
        "hf_gguf": "https://huggingface.co/api/models?filter=gguf&sort=downloads&limit=100",
        "hf_recent": "https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=100",
        "hf_trending": "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=100",
        # ── Ollama Register (official models, China + Europe included) ──
        "ollama": "https://ollama.com/api/tags",
        # ── Direct free tier APIs ──
        "groq": "https://api.groq.com/openai/v1/models",
        "cerebras": "https://api.cerebras.ai/v1/models",
        "mistral": "https://api.mistral.ai/v1/models",
        "together": "https://api.together.xyz/v1/models",
        "fireworks": "https://api.fireworks.ai/inference/v1/models",
        "deepseek": "https://api.deepseek.com/v1/models",
        "nvidia": "https://integrate.api.nvidia.com/v1/models",
        "cloudflare": "https://api.cloudflare.com/client/v4/accounts",
        "cohere": "https://api.cohere.com/v1/models",
        "modelscope": "https://www.modelscope.cn/api/v1/models",
        "siliconflow": "https://api.siliconflow.cn/v1/models",
        "glm": "https://open.bigmodel.cn/api/paas/v4/models",
        # ── Ollama / Open-source hubs ──
        "ollama_cloud": "https://api.openwebui.com/api/models",
        "llm7": "https://api.llm7.io/v1/models",
    }

    # GGUF architectures of LANGUAGE models. A GGUF repository of audio,
    # vision or embeddings is not a cat model: we dismiss it.
    LLM_ARCHS = {
        "llama", "llama2", "llama3", "llama4", "qwen2", "qwen3", "qwen3moe",
        "qwen35", "gemma", "gemma2", "gemma3", "gemma4", "phi2", "phi3", "phi4",
        "mistral", "mixtral", "gpt2", "gptneox", "falcon", "falcon-moe",
        "deepseek", "deepseek2", "deepseek3", "glm4", "glm4moe", "minicpm",
        "minicpm3", "internlm2", "internlm3", "command-r", "exaone", "exaone4",
        "olmo", "olmo2", "olmo3", "smollm3", "granite", "granitemoe", "starcoder",
        "starcoder2", "chameleon", "dbrx", "nemotron", "hunyuan",
        "ernie4_5", "seed_oss", "dots1", "arcee", "cohere2", "dbrx2", "gpt-oss",
    }
    # We explicitly exclude embedding and media architectures.
    NON_LLM_ARCHS = {
        "bert", "roberta", "t5", "mert2", "acestep-lm", "whisper", "wav2vec2",
        "clip", "siglip", "vit", "sam", "rn-bert", "nomic-bert", "jina-bert",
    }

    # Origin of the laboratory which publishes the model. Used to NOT IGNORE the
    # Chinese and European labs: they are tagged, filterable and displayed.
    ORIGIN_RULES = [
        # ── Chine ──
        ("qwen", "cn", "Chine (Alibaba)"),
        ("deepseek", "cn", "Chine (DeepSeek)"),
        ("zai-org", "cn", "Chine (Zhipu/GLM)"),
        ("z-ai", "cn", "Chine (Zhipu/GLM)"),
        ("glm", "cn", "Chine (Zhipu/GLM)"),
        ("moonshot", "cn", "Chine (Moonshot/Kimi)"),
        ("kimi", "cn", "Chine (Moonshot/Kimi)"),
        ("minimax", "cn", "Chine (MiniMax)"),
        ("internlm", "cn", "Chine (Shanghai AI Lab)"),
        ("baichuan", "cn", "Chine (Baichuan)"),
        ("hunyuan", "cn", "Chine (Tencent)"),
        ("doubao", "cn", "Chine (ByteDance)"),
        ("bytedance", "cn", "Chine (ByteDance)"),
        ("skywork", "cn", "Chine (Skywork)"),
        ("ernie", "cn", "Chine (Baidu)"),
        ("01-ai", "cn", "Chine (01.AI)"),
        ("yi-", "cn", "Chine (01.AI)"),
        ("openbmb", "cn", "Chine (OpenBMB)"),
        ("infini", "cn", "Chine (Infini-AI)"),
        ("telecom", "cn", "Chine (China Telecom)"),
        ("tencent", "cn", "Chine (Tencent)"),
        ("stepfun", "cn", "Chine (StepFun)"),
        # ── Europe ──
        ("mistral", "eu", "Europe (Mistral AI, FR)"),
        ("eurollm", "eu", "Europe (EuroLLM)"),
        ("utter-project", "eu", "Europe (EuroLLM)"),
        ("apertus", "eu", "Europe (Swiss AI, CH)"),
        ("swiss-ai", "eu", "Europe (Swiss AI, CH)"),
        ("jina", "eu", "Europe (Jina AI, DE)"),
        ("aleph", "eu", "Europe (Aleph Alpha, DE)"),
        ("bloom", "eu", "Europe (BigScience)"),
        # ── North America / rest of the world ──
        ("granite", "us", "United States (IBM)"),
        ("cohere", "ca", "Canada (Cohere)"),
        ("ai21", "il", "Israel (AI21)"),
        ("naver", "kr", "Coree (Naver)"),
        ("hyperclova", "kr", "Coree (Naver)"),
        ("falcon", "ae", "E.A.U. (TII Falcon)"),
        ("openai", "us", "United States (OpenAI)"),
        ("gpt-", "us", "United States (OpenAI)"),
        ("anthropic", "us", "United States (Anthropic)"),
        ("claude", "us", "United States (Anthropic)"),
        ("google", "us", "United States (Google)"),
        ("gemini", "us", "United States (Google)"),
        ("meta-llama", "us", "United States (Meta)"),
        ("llama", "us", "United States (Meta)"),
        ("nvidia", "us", "United States (NVIDIA)"),
        ("microsoft", "us", "United States (Microsoft)"),
        ("xai", "us", "United States (xAI)"),
        ("grok", "us", "United States (xAI)"),
        ("perplexity", "us", "United States (Perplexity)"),
        ("openai-", "us", "United States (OpenAI)"),
    ]

    # Live stream: recent releases and announcements.
    NEWS_FEEDS = [
        ("Hugging Face — Papers of the Day", "https://huggingface.co/api/daily_papers?limit=30", "json"),
        ("Hugging Face — Blog", "https://huggingface.co/blog/feed.xml", "rss"),
        ("r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/.rss", "rss"),
        ("Hacker News", "https://news.ycombinator.com/rss", "rss"),
        ("OpenAI — News", "https://openai.com/news/rss.xml", "rss"),
        ("Google AI — Blog", "https://blog.google/technology/ai/rss/", "rss"),
    ]

    # Local applications: directory + executables. They are NEVER
    # in the PATH, you must therefore search in the installation folders.
    DESKTOP_APP_TARGETS = {
        "lmstudio": (["LM Studio", "lm-studio", "LM-Studio"], ["LM Studio.exe", "LM-Studio.exe"]),
        "jan": (["Jan", "jan"], ["Jan.exe", "jan.exe"]),
        "cherry": (["Cherry Studio", "cherry-studio"], ["Cherry Studio.exe", "cherry-studio.exe"]),
        "unsloth": (["Unsloth", "unsloth"], ["unsloth.exe", "Unsloth.exe", "Unsloth Desktop.exe"]),
        "ollama": (["Ollama"], ["ollama.exe", "Ollama.exe"]),
        "gpt4all": (["GPT4All", "gpt4all"], ["gpt4all.exe", "GPT4All.exe"]),
        "koboldcpp": (["KoboldCpp", "koboldcpp"], ["koboldcpp.exe", "KoboldCpp.exe"]),
        "llamacpp": (["llama.cpp", "Llama.cpp"], ["server.exe", "llama-cli.exe"]),
        "anythingllm": (["AnythingLLM", "anythingllm"], ["AnythingLLM.exe"]),
        "librechat": (["LibreChat", "librechat"], ["librechat.exe"]),
        "open-webui": (["open-webui", "Open WebUI"], ["open-webui.exe"]),
        "msty": (["Msty", "msty"], ["Msty.exe", "msty.exe"]),
        "chatbox": (["Chatbox", "chatbox"], ["Chatbox.exe"]),
        "mlc-chat": (["mlc-chat", "MLC Chat"], ["mlc_chat.exe"]),
        "drawthings": (["Draw Things", "draw-things"], ["Draw Things.exe"]),
        "pinokio": (["pinokio", "Pinokio"], ["pinokio.exe"]),
        "localpilot": (["LocalPilot", "localpilot"], ["LocalPilot.exe"]),
        "exo": (["exo", "Exo"], ["exo.exe"]),
        "text-generation-webui": (["text-generation-webui", "oobabooga"], ["run.bat", "webui.bat"]),
        "privategpt": (["PrivateGPT", "privategpt"], ["PrivateGPT.exe"]),
        "quark": (["Quark", "quark"], ["quark.exe"]),
    }

    # Desktop AI apps to detect (local installs)
    DESKTOP_APPS = [
        "lmstudio", "ollama", "jan", "gpt4all", "koboldcpp",
        "text-generation-webui", "mlc-chat", "llamacpp",
        "chatbox", "msty", "anythingllm", "librechat", "open-webui",
        "privategpt", "quark", "chatall", "pot", "gpt-runner",
        "lmstudio-cpp", "exo", "amos", "pinokio", "localpilot",
        # ── Ajouts 2026-10: apps IA locales demandees ──
        "cherry", "cherry-studio", "unsloth", "lm-studio", "drawthings",
    ]

    FRONTIER_KEYWORDS = [
        "gpt-4", "gpt-4o", "gpt-5", "o1", "o3", "o4",
        "claude-3", "claude-3.5", "claude-3-7", "claude-4", "sonnet", "opus", "haiku",
        "gemini-1.5", "gemini-2", "gemini-3", "gemini-pro", "gemini-flash",
        "qwen-2.5", "qwen2.5", "qwen3", "qwen3.5", "qwen-max", "qwen-next",
        "deepseek-v3", "deepseek-v4", "deepseek-r1", "deepseek-r2",
        "llama-3.1", "llama-3.2", "llama-3.3", "llama-4", "llama-4-maverick", "llama-4-scout",
        "nemotron", "nemotron-3", "nemotron-4",
        "command-r", "command-r+", "command-a",
        "jamba", "yi-34b", "yi-large", "gemma-2", "gemma-3",
        "mistral-large", "mistral-medium", "codestral", "pixtral",
        "ministral", "magistral",
        "dbrx", "yi-lightning", "moonshot", "kimi",
        "grok-2", "grok-3", "grok-4",
        "perplexity", "sonar", "sonar-pro",
        "phi-4", "phi-5",
        "glm-4", "glm-5", "glm-next",
        "exaone", "exaone-4",
        "argon", "selene", "evol",
    ]

    EXCLUDE_KEYWORDS = [
        "mini", "small", "tiny", "1b", "3b", "7b", "8b", "13b",
        "quantized", "gguf", "awq", "gptq", "distil", "lite",
    ]

    def __init__(self, catalog_path="data/free_models_catalog.json", scan_interval=300,
                 min_tier=ModelTier.FRONTIER, on_discovery=None):
        self.catalog_path = Path(catalog_path)
        self.scan_interval = scan_interval
        self.min_tier = min_tier
        self.on_discovery = on_discovery
        self.catalog = {}
        self._running = False
        self._task = None
        self.news = []
        # compat Roma
        self.discovered_endpoints = []

    def _is_frontier(self, model_id):
        model_lower = model_id.lower()
        for kw in self.EXCLUDE_KEYWORDS:
            if kw in model_lower:
                return False
        for kw in self.FRONTIER_KEYWORDS:
            if kw in model_lower:
                return True
        return False

    def _origin(self, model_id: str) -> Dict[str, str]:
        """Origin of the laboratory (China / Europe / ...). Rule by pattern."""
        m = (model_id or "").lower()
        for pat, code, label in self.ORIGIN_RULES:
            if pat in m:
                return {"code": code, "label": label}
        return {"code": "other", "label": "Autre"}

    def _estimate_tier(self, model_id):
        m = model_id.lower()
        # Tailles explicites (dense et MoE "120b-a12b")
        import re
        sizes = [int(x) for x in re.findall(r"(\d+)b", m)]
        max_b = max(sizes) if sizes else 0
        if max_b >= 200:
            return ModelTier.FRONTIER
        if any(k in m for k in ["gpt-4", "claude-3.5", "claude-3-7", "claude-4", "gemini-1.5-pro", "gemini-2", "gemini-3",
                                "qwen-max", "qwen3", "deepseek-v3", "deepseek-v4", "llama-3.1-405b", "llama-4", "nemotron-3-ultra"]):
            return ModelTier.FRONTIER
        if max_b >= 60:
            return ModelTier.LARGE
        if any(k in m for k in ["32b", "34b"]):
            return ModelTier.LARGE
        if any(k in m for k in ["7b", "8b", "13b", "14b", "16b", "20b", "24b", "30b"]):
            return ModelTier.MEDIUM
        return ModelTier.SMALL


    async def scan_openrouter_free(self):
        """Compat Roma: returns the list of :free model IDs."""
        models = await self.scan_openrouter()
        return [m.model_id for m in models]

    async def scan_openrouter(self):
        models = []
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.SOURCES["openrouter"]) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("data", []):
                            model_id = item.get("id", "")
                            if ":free" in model_id and self._is_frontier(model_id):
                                ctx = item.get("context_length")
                                models.append(FreeModel(
                                    model_id=model_id,
                                    provider="openrouter",
                                    tier=self._estimate_tier(model_id),
                                    context_window=ctx if isinstance(ctx, int) and ctx > 0 else None,
                                    metadata={
                                        "name": item.get("name"),
                                        "pricing": item.get("pricing"),
                                        "ctx_source": "openrouter:context_length" if ctx else "",
                                        "origin": self._origin(model_id),
                                    },
                                ))
        except Exception as e:
            _log("[FreeHunter] OpenRouter scan failed: " + str(e))
        return models

    async def scan_huggingface(self):
        models = []
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.SOURCES["huggingface"]) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data[:50]:
                            model_id = item.get("modelId", "")
                            if self._is_frontier(model_id):
                                models.append(FreeModel(
                                    model_id=model_id,
                                    provider="huggingface",
                                    tier=self._estimate_tier(model_id),
                                    metadata={
                                        "downloads": item.get("downloads", 0),
                                        "likes": item.get("likes", 0),
                                        "pipeline_tag": item.get("pipeline_tag", ""),
                                        "ctx_source": "",
                                        "origin": self._origin(model_id),
                                    },
                                ))
        except Exception as e:
            _log("[FreeHunter] HuggingFace scan failed: " + str(e))
        return models

    async def scan_huggingface_gguf(self):
        """Depots GGUF HuggingFace.

        This is the most accurate source in the catalog:
          - the REAL context window is in the GGUF metadata
            (`gguf.context_length`) of the file, not guessed;
          - the quantification files are the REAL files from the repository,
            with their REAL size in bytes.
        """
        models = []
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.SOURCES["hf_gguf"]) as resp:
                    if resp.status != 200:
                        _log("[FreeHunter] HF GGUF list HTTP " + str(resp.status))
                        return models
                    repos = await resp.json()
                if not isinstance(repos, list):
                    return models
                for item in repos[:40]:
                    repo = item.get("id") or item.get("modelId")
                    if not repo:
                        continue
                    try:
                        async with session.get(
                            "https://huggingface.co/api/models/" + repo + "?blobs=true"
                        ) as r2:
                            if r2.status != 200:
                                continue
                            detail = await r2.json()
                    except Exception:
                        continue
                    gguf = detail.get("gguf") or {}
                    card = detail.get("cardData") or {}
                    # We only keep the TEXT models: a GGUF repository
                    # audio or vision is not a chat model.
                    pipeline = (detail.get("pipeline_tag") or item.get("pipeline_tag") or "").lower()
                    arch = (gguf.get("architecture") or "").lower()
                    is_llm = ((pipeline == "text-generation") or (arch in self.LLM_ARCHS)) \
                        and arch not in self.NON_LLM_ARCHS
                    if not is_llm:
                        continue
                    ctx = gguf.get("context_length")
                    files = []
                    for sib in (detail.get("siblings") or []):
                        fn = sib.get("rfilename") or ""
                        if not fn.lower().endswith(".gguf"):
                            continue
                        size = sib.get("size") or (sib.get("lfs") or {}).get("size") or 0
                        files.append({
                            "file": fn,
                            "quant": _gguf_quant(fn),
                            "size_bytes": int(size or 0),
                            "url": "https://huggingface.co/" + repo + "/resolve/main/" + fn,
                        })
                    if not files:
                        continue
                    # We keep the useful quantifications (the most used
                    # locally) + f16. Not the 25 IQ experimental.
                    files.sort(key=lambda f: f["size_bytes"])
                    keep = [f for f in files if f["quant"].upper() in (
                        "Q2_K", "Q3_K_M", "Q4_0", "Q4_K_M", "Q4_K_S", "Q5_0",
                        "Q5_K_M", "Q6_K", "Q8_0", "F16", "IQ3_M", "IQ4_XS")]
                    if not keep:
                        keep = files[:6]
                    models.append(FreeModel(
                        model_id="hf-gguf/" + repo,
                        provider="huggingface:gguf",
                        tier=self._estimate_tier(repo),
                        context_window=ctx if isinstance(ctx, int) and ctx > 0 else None,
                        metadata={
                            "name": repo,
                            "base_model": card.get("base_model"),
                            "architecture": gguf.get("architecture"),
                            "license": card.get("license"),
                            "downloads": item.get("downloads", 0),
                            "likes": item.get("likes", 0),
                            "download_modes": keep,
                            "download_count": len(files),
                            "total_size_bytes": gguf.get("total"),
                            "ctx_source": "huggingface:gguf" if ctx else "",
                            "origin": self._origin(repo),
                        },
                    ))
        except Exception as e:
            _log("[FreeHunter] HF GGUF scan failed: " + str(e))
        return models

    async def scan_huggingface_recent(self):
        """Live releases: recently created HF models + trending models."""
        models = []
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for source, url in (("hf_recent", self.SOURCES["hf_recent"]),
                                     ("hf_trending", self.SOURCES["hf_trending"])):
                    try:
                        async with session.get(url) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.json()
                    except Exception:
                        continue
                    if not isinstance(data, list):
                        continue
                    for item in data[:80]:
                        mid = item.get("id") or item.get("modelId")
                        if not mid or not self._is_frontier(mid):
                            continue
                        models.append(FreeModel(
                            model_id=mid,
                            provider=source,
                            tier=self._estimate_tier(mid),
                            metadata={
                                "name": mid,
                                "downloads": item.get("downloads", 0),
                                "likes": item.get("likes", 0),
                                "trending_score": item.get("trendingScore"),
                                "created_at": item.get("createdAt"),
                                "last_modified": item.get("lastModified"),
                                "pipeline_tag": item.get("pipeline_tag", ""),
                                "is_new": source == "hf_recent",
                                "ctx_source": "",
                                "origin": self._origin(mid),
                            },
                        ))
        except Exception as e:
            _log("[FreeHunter] HF recent scan failed: " + str(e))
        return models

    async def scan_ollama(self):
        """Ollama register: official models, Chinese and European labs included."""
        models = []
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.SOURCES["ollama"]) as resp:
                    if resp.status != 200:
                        _log("[FreeHunter] Ollama HTTP " + str(resp.status))
                        return models
                    data = await resp.json()
                for item in (data.get("models") or []):
                    name = item.get("name") or item.get("model")
                    if not name:
                        continue
                    det = item.get("details") or {}
                    models.append(FreeModel(
                        model_id="ollama/" + name,
                        provider="ollama",
                        tier=self._estimate_tier(name),
                        metadata={
                            "name": name,
                            "size_bytes": item.get("size", 0),
                            "parameter_size": det.get("parameter_size", ""),
                            "quantization": det.get("quantization_level", ""),
                            "family": det.get("family", ""),
                            "capabilities": item.get("capabilities") or [],
                            "modified_at": item.get("modified_at"),
                            "download": "ollama pull " + name,
                            "ctx_source": "",
                            "origin": self._origin(name),
                        },
                    ))
        except Exception as e:
            _log("[FreeHunter] Ollama scan failed: " + str(e))
        return models

    # ── LIVE NEWS ────────────────────────────────────────────────────────
    @staticmethod
    def _parse_rss(text: str, source: str) -> List[Dict]:
        items = []
        try:
            root = ET.fromstring(text)
        except Exception:
            return items
        for node in root.iter():
            if node.tag.split("}")[-1] not in ("item", "entry"):
                continue
            title = link = date = summary = ""
            for ch in list(node):
                ct = ch.tag.split("}")[-1]
                if ct == "title" and not title:
                    title = (ch.text or "").strip()
                elif ct == "link" and not link:
                    link = (ch.text or "").strip() or (ch.attrib.get("href") or "").strip()
                elif ct in ("pubDate", "published", "updated") and not date:
                    date = (ch.text or "").strip()
                elif ct == "description" and not summary:
                    summary = (ch.text or "").strip()
            if title:
                items.append({
                    "title": title, "link": link, "date": date,
                    "source": source, "summary": summary[:280],
                })
        return items

    async def scan_news(self) -> List[Dict]:
        """Live feed of recent releases and announcements (RSS + JSON)."""
        out = []
        try:
            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async def grab(url):
                    async with session.get(url, headers={"User-Agent": "ViaRoma/1.0"}) as resp:
                        if resp.status != 200:
                            return None
                        return await resp.text()

                async def grab_json(url):
                    async with session.get(url, headers={"User-Agent": "ViaRoma/1.0"}) as resp:
                        if resp.status != 200:
                            return None
                        return await resp.json()

                for label, url, kind in self.NEWS_FEEDS:
                    try:
                        if kind == "rss":
                            text = await grab(url)
                            if not text:
                                continue
                            out.extend(self._parse_rss(text, label))
                        else:
                            data = await grab_json(url)
                            if not isinstance(data, list):
                                continue
                            for item in data:
                                paper = item.get("paper") or {}
                                out.append({
                                    "title": item.get("title") or paper.get("title") or "",
                                    "link": paper.get("projectPage")
                                            or paper.get("githubRepo")
                                            or ("https://huggingface.co/papers/" + str(paper.get("id", ""))),
                                    "date": paper.get("submittedOnDailyAt") or paper.get("publishedAt") or "",
                                    "source": label,
                                    "summary": (item.get("summary") or paper.get("summary") or "")[:280],
                                    "upvotes": paper.get("upvotes"),
                                })
                    except Exception:
                        continue
        except Exception as e:
            _log("[FreeHunter] News scan failed: " + str(e))
        self.news = out
        return out

    def get_news(self) -> List[Dict]:
        return getattr(self, "news", [])

    async def _scan_generic_openai_api(self, source_name):
        """Scan any OpenAI-compatible /v1/models endpoint (no key needed for free tiers)."""
        models = []
        url = self.SOURCES.get(source_name)
        if not url:
            return models
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            headers = {"Authorization": "Bearer placeholder"}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status in (200, 401, 403):
                        try:
                            data = await resp.json()
                        except Exception:
                            return models
                        if not isinstance(data, dict):
                            return models
                        # items can be None on a source that returns
                        # {"data": null}: we do not loop on None.
                        items = data.get("data")
                        if not isinstance(items, list):
                            items = data.get("models")
                        if not isinstance(items, list):
                            items = []
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            model_id = item.get("id", item.get("name", ""))
                            if not model_id or not self._is_frontier(model_id):
                                continue
                            ctx = item.get("context_length")
                            if not isinstance(ctx, int) or ctx <= 0:
                                ctx = item.get("max_tokens")
                            if not isinstance(ctx, int) or ctx <= 0:
                                ctx = None
                            models.append(FreeModel(
                                model_id=f"{source_name}/{model_id}",
                                provider=source_name,
                                tier=self._estimate_tier(model_id),
                                context_window=ctx,
                                metadata={
                                    "name": item.get("name", ""),
                                    "source": source_name,
                                    "ctx_source": (source_name + ":context_length") if ctx else "",
                                    "origin": self._origin(model_id),
                                },
                            ))
        except Exception as e:
            _log(f"[FreeHunter] {source_name} scan failed: {e}")
        return models

    async def scan_desktop_apps(self):
        """Detect locally installed desktop AI apps.

        PATH + Windows installation folders (apps like LM Studio,
        Cherry Studio, Jan or Unsloth are NEVER in the PATH).
        """
        import subprocess, shutil, os
        found = []
        seen_exe = set()
        for app in self.DESKTOP_APPS:
            app_clean = app.strip()
            exe = shutil.which(app_clean) or shutil.which(app_clean.replace("-", ""))
            if exe and exe not in seen_exe:
                seen_exe.add(exe)
                found.append(FreeModel(
                    model_id=f"desktop/{app_clean}",
                    provider="desktop",
                    tier=ModelTier.SMALL,
                    metadata={"name": app_clean, "exe": exe, "type": "local_app",
                              "origin": self._origin(app_clean)},
                ))
        # Windows installation folders.
        roots = []
        for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(var)
            if base:
                roots.append(os.path.join(base, "Programs"))
                roots.append(base)
        for app_id, (folders, exes) in self.DESKTOP_APP_TARGETS.items():
            for root in roots:
                if not os.path.isdir(root):
                    continue
                for folder in folders:
                    d = os.path.join(root, folder)
                    if not os.path.isdir(d):
                        continue
                    for exe_name in exes:
                        p = os.path.join(d, exe_name)
                        if os.path.isfile(p) and p not in seen_exe:
                            seen_exe.add(p)
                            found.append(FreeModel(
                                model_id=f"desktop/{app_id}",
                                provider="desktop:app",
                                tier=ModelTier.SMALL,
                                metadata={"name": app_id, "exe": p, "type": "local_app",
                                          "install_dir": d,
                                          "origin": self._origin(app_id)},
                            ))
                            break
        # Check common local API endpoints
        for port_name, port in [("lmstudio", 1234), ("ollama", 11434), ("open-webui", 8080), ("librechat", 3080), ("jan", 3000)]:
            try:
                timeout = aiohttp.ClientTimeout(total=3)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"http://127.0.0.1:{port}/v1/models") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for item in data.get("data", []):
                                found.append(FreeModel(
                                    model_id=f"desktop/{port_name}/{item.get('id','')}",
                                    provider=f"desktop:{port_name}",
                                    tier=self._estimate_tier(item.get("id", "")),
                                    metadata={"port": port, "endpoint": f"127.0.0.1:{port}",
                                              "origin": self._origin(item.get("id", ""))},
                                ))
            except Exception:
                pass
        return found

    async def scan_all_sources(self):
        """Scan ALL configured sources worldwide + desktop apps in parallel."""
        scan_tasks = [
            self.scan_openrouter(),
            self.scan_huggingface(),
            self.scan_huggingface_gguf(),
            self.scan_huggingface_recent(),
            self.scan_ollama(),
            self.scan_desktop_apps(),
        ]
        # Add generic API scanners for all new sources
        for src in ["groq", "cerebras", "mistral", "together", "fireworks", "deepseek",
                     "nvidia", "cloudflare", "cohere", "modelscope", "siliconflow",
                     "glm", "ollama_cloud", "llm7"]:
            scan_tasks.append(self._scan_generic_openai_api(src))
        results = await asyncio.gather(*scan_tasks, return_exceptions=True)
        all_models = []
        for r in results:
            if isinstance(r, list):
                all_models.extend(r)
        return all_models


    # --- Catalogue ---

    def load_catalog(self):
        if not self.catalog_path.exists():
            return
        try:
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            dropped = 0
            for mid, mdata in data.items():
                # Cleanup: a GGUF audio/embeddings repository is not a
                # cat model. It could have been cataloged before the filter.
                if str(mid).startswith("hf-gguf/"):
                    arch = str((mdata.get("metadata") or {}).get("architecture") or "").lower()
                    if arch and (arch in self.NON_LLM_ARCHS or arch not in self.LLM_ARCHS):
                        dropped += 1
                        continue
                self.catalog[mid] = FreeModel.from_dict(mdata)
            if dropped:
                _log("[FreeHunter] " + str(dropped) + " non-LLM GGUF entries removed")
            _log("[FreeHunter] Loaded " + str(len(self.catalog)) + " models from catalog")
        except Exception as e:
            _log("[FreeHunter] Failed to load catalog: " + str(e))

    def save_catalog(self):
        try:
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            data = {mid: m.to_dict() for mid, m in self.catalog.items()}
            self.catalog_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            _log("[FreeHunter] Failed to save catalog: " + str(e))

    def merge_discovered(self, new_models):
        added = 0
        upgraded = 0
        for model in new_models:
            if model.model_id not in self.catalog:
                self.catalog[model.model_id] = model
                added += 1
                if self.on_discovery:
                    try:
                        self.on_discovery(model)
                    except Exception:
                        pass
            else:
                existing = self.catalog[model.model_id]
                existing.last_verified = time.time()
                existing.is_active = True
                # A REAL context window replaces a value
                # absent (or the old 32768 manufactured).
                if model.context_window and not existing.context_window:
                    existing.context_window = model.context_window
                    upgraded += 1
                # The same goes for GGUF download modes.
                if (model.metadata.get("download_modes")
                        and not existing.metadata.get("download_modes")):
                    existing.metadata.update(model.metadata)
                    upgraded += 1
                # Backfill of the origin of the lab and the source of the ctx
                # on old entries (created before these fields).
                md = existing.metadata
                if not md.get("origin"):
                    md["origin"] = model.metadata.get("origin") or self._origin(existing.model_id)
                    upgraded += 1
                if model.metadata.get("ctx_source") and not md.get("ctx_source"):
                    md["ctx_source"] = model.metadata["ctx_source"]
        if upgraded:
            _log("[FreeHunter] " + str(upgraded) + " enriched model(s) (real ctx / GGUF)")
        return added

    def get_active_frontier_models(self):
        return [m for m in self.catalog.values() if m.is_active and m.tier == ModelTier.FRONTIER]

    def get_recent_models(self, limit=40):
        """Live releases: the most recently released models, all third parties."""
        items = []
        for m in self.catalog.values():
            ts = (m.metadata or {}).get("created_at") or (m.metadata or {}).get("last_modified")
            if not ts:
                continue
            items.append((str(ts), m))
        items.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in items[:limit]]

    def get_gguf_models(self, limit=200):
        """Models with REAL GGUF download modes."""
        out = [m for m in self.catalog.values() if (m.metadata or {}).get("download_modes")]
        out.sort(key=lambda m: -(m.metadata.get("downloads") or 0))
        return out[:limit]

    # --- Boucle ---

    async def run_discovery_loop(self, interval_seconds=None):
        """Compat Roma: intervalle surchargeable, sinon scan_interval."""
        interval = interval_seconds or self.scan_interval
        self._running = True
        self.load_catalog()
        _log("[FreeHunter] Initial scan...")
        new_models = await self.scan_all_sources()
        added = self.merge_discovered(new_models)
        if added:
            _log("[FreeHunter] Discovered " + str(added) + " new frontier models")
        try:
            await self.scan_news()
        except Exception:
            pass
        self.save_catalog()
        self.discovered_endpoints = [m.model_id for m in new_models]
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            _log("[FreeHunter] Periodic scan...")
            new_models = await self.scan_all_sources()
            added = self.merge_discovered(new_models)
            if added:
                _log("[FreeHunter] Discovered " + str(added) + " new frontier models")
            try:
                await self.scan_news()
            except Exception:
                pass
            self.save_catalog()
            self.discovered_endpoints = [m.model_id for m in new_models]

    def start(self, interval_seconds=None):
        """Starts the loop in the background."""
        self._task = asyncio.create_task(self.run_discovery_loop(interval_seconds))
        return self._task

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    def get_stats(self):
        by_origin = {}
        ctx_known = 0
        ctx_unknown = 0
        gguf_models = 0
        for m in self.catalog.values():
            org = (m.metadata.get("origin") or {}).get("code", "other")
            by_origin[org] = by_origin.get(org, 0) + 1
            if m.context_window:
                ctx_known += 1
            else:
                ctx_unknown += 1
            if m.metadata.get("download_modes"):
                gguf_models += 1
        return {
            "total_models": len(self.catalog),
            "by_tier": {t.value: sum(1 for m in self.catalog.values() if m.tier == t) for t in ModelTier},
            "by_provider": {p: sum(1 for m in self.catalog.values() if m.provider == p) for p in set(m.provider for m in self.catalog.values())},
            "by_origin": by_origin,
            "context_known": ctx_known,
            "context_unknown": ctx_unknown,
            "gguf_models": gguf_models,
            "active_frontier": len(self.get_active_frontier_models()),
            "last_scan": max((m.last_verified for m in self.catalog.values()), default=0),
            "news_count": len(getattr(self, "news", [])),
        }
