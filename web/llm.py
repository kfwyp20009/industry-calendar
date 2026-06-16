"""LLM 多厂商接入模块 — 支持 DeepSeek / OpenAI / Anthropic / Ollama"""

import os
import json
import re
import time
import hashlib
import http.client
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlparse

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "llm_config.yaml")
CACHE_FILE = os.path.join(BASE_DIR, "data", "analysis_cache.yaml")
PROMPTS_FILE = os.path.join(BASE_DIR, "data", "prompts.yaml")
CACHE_TTL_HOURS = 24

# 内置厂商定义
BUILTIN_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "docs_url": "https://platform.deepseek.com/api_keys",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini"],
        "default_model": "gpt-4o",
        "docs_url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "models": ["claude-sonnet-4-20250514", "claude-haiku-3-5-20241022"],
        "default_model": "claude-sonnet-4-20250514",
        "docs_url": "https://console.anthropic.com/",
    },
    "google": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "default_model": "gemini-2.5-flash",
        "docs_url": "https://aistudio.google.com/apikey",
    },
    "siliconflow": {
        "name": "SiliconFlow (硅基流动)",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-72B-Instruct"],
        "default_model": "deepseek-ai/DeepSeek-V3",
        "docs_url": "https://cloud.siliconflow.cn/",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-air", "glm-4-flash"],
        "default_model": "glm-4-flash",
        "docs_url": "https://open.bigmodel.cn/",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "default_model": "llama-3.3-70b-versatile",
        "docs_url": "https://console.groq.com/keys",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["auto"],
        "default_model": "auto",
        "docs_url": "https://openrouter.ai/keys",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "base_url": "http://localhost:11434",
        "models": ["llama3", "qwen2.5", "deepseek-r1"],
        "default_model": "qwen2.5",
        "docs_url": None,
    },
}


def get_custom_providers(config=None):
    """获取自定义厂商列表"""
    if config is None:
        config = load_config()
    return config.get("custom_providers", {})


def add_custom_provider(key, name, base_url, models, api_key="", model=""):
    """添加自定义厂商"""
    config = load_config()
    custom = config.setdefault("custom_providers", {})
    if key in custom:
        return False, f"标识 '{key}' 已存在"
    custom[key] = {
        "name": name,
        "base_url": base_url,
        "models": models.split(",") if isinstance(models, str) else models,
        "model": model or (models.split(",")[0] if isinstance(models, str) else models[0]),
        "api_key": api_key,
        "enabled": False,
    }
    save_config(config)
    return True, "添加成功"


def detect_models(base_url, api_key=""):
    """从 OpenAI 兼容的 /v1/models 端点探测可用模型列表"""
    url = base_url.rstrip("/") + "/models"
    # 如果 base_url 已经以 /models 结尾则不再追加
    if "/models" in base_url:
        url = base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        models = [m["id"] for m in result.get("data", []) if m.get("id")]
        # 过滤掉嵌入类、tts类等非对话模型
        chat_models = [m for m in models if not any(
            skip in m.lower() for skip in ["embed", "tts", "whisper", "moderation", "davinci", "babbage"])
        ]
        return chat_models or models, None
    except Exception as e:
        return None, str(e)


def remove_custom_provider(key):
    """删除自定义厂商"""
    config = load_config()
    custom = config.get("custom_providers", {})
    if key not in custom:
        return False, "未找到该厂商"
    del custom[key]
    save_config(config)
    return True, "删除成功"


# Provider key → 环境变量名映射
ENV_KEY_MAP = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _apply_env_overrides(config):
    """用环境变量覆盖配置中的 API Key（环境变量优先级最高）"""
    providers = config.get("providers", {})
    for key, env_name in ENV_KEY_MAP.items():
        env_val = os.environ.get(env_name, "").strip()
        if env_val and key in providers:
            providers[key]["api_key"] = env_val
    # 自定义厂商：按命名约定 KEY_<大写标识>
    custom = config.get("custom_providers", {})
    for key in custom:
        env_name = f"KEY_{key.upper()}"
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            custom[key]["api_key"] = env_val
    return config


def load_config():
    """加载 LLM 配置（环境变量中的 API Key 会覆盖配置文件）"""
    if not os.path.exists(CONFIG_FILE):
        return _apply_env_overrides(_default_config())
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _apply_env_overrides(data)


def _default_config():
    return {
        "providers": {
            key: {
                "enabled": key == "deepseek",
                "api_key": "",
                "base_url": info["base_url"],
                "model": info["default_model"],
            }
            for key, info in BUILTIN_PROVIDERS.items()
        },
        "default_provider": "deepseek",
        "updated": "",
    }


def save_config(config):
    """保存 LLM 配置"""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    config["updated"] = time.strftime("%Y-%m-%d %H:%M")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)


# ── 分析结果缓存 ──

def _cache_key(industry, provider, extra=""):
    """生成缓存键（MD5）"""
    raw = f"{industry}|{provider}|{extra}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _get_cached(key):
    """读取缓存，过期返回 None"""
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entry = data.get("caches", {}).get(key)
    if not entry:
        return None
    expires = entry.get("expires")
    if expires and datetime.now() > datetime.fromisoformat(expires):
        return None
    return entry.get("content")


def _save_cache(key, content, industry, provider, extra=""):
    """写入缓存"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = yaml.safe_load(f) or {}
    if "caches" not in cache:
        cache["caches"] = {}
    cache["caches"][key] = {
        "content": content,
        "industry": industry,
        "provider": provider,
        "extra": extra,
        "created": datetime.now().isoformat(timespec="minutes"),
        "expires": (datetime.now() + timedelta(hours=CACHE_TTL_HOURS)).isoformat(timespec="minutes"),
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cache, f, allow_unicode=True, sort_keys=False)


def get_default_provider():
    """获取默认厂商 key"""
    config = load_config()
    return config.get("default_provider", "deepseek")


def set_default_provider(provider_key):
    """设置默认厂商"""
    config = load_config()
    # 检查厂商是否存在（内置或自定义）
    if provider_key in BUILTIN_PROVIDERS or provider_key in config.get("custom_providers", {}):
        config["default_provider"] = provider_key
        save_config(config)
        return True, "已设为默认"
    return False, "厂商不存在"


def get_enabled_providers():
    """获取已启用的厂商列表（含自定义厂商）"""
    config = load_config()
    providers = config.get("providers", {})
    result = [(key, info) for key, info in providers.items() if info.get("enabled")]
    # 加入已启用的自定义厂商
    for key, info in config.get("custom_providers", {}).items():
        if info.get("enabled"):
            result.append((key, info))
    return result


# ── Prompt 模板管理 ──

def load_prompts():
    """加载 Prompt 模板配置"""
    if not os.path.exists(PROMPTS_FILE):
        return {"presets": {}}
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"presets": {}}


def get_preset_prompt(preset_key, prompt_type):
    """获取指定预设的 Prompt 文本，fallback 到内置默认"""
    prompts_data = load_prompts()
    presets = prompts_data.get("presets", {})
    if preset_key in presets:
        text = presets[preset_key].get(prompt_type, "")
        if text:
            return text
    # fallback
    if prompt_type == "industry_report":
        return INDUSTRY_REPORT_PROMPT
    elif prompt_type == "calendar_generation":
        return CALENDAR_GENERATION_PROMPT
    return ""


def get_available_presets():
    """获取可用的预设列表"""
    prompts_data = load_prompts()
    presets = prompts_data.get("presets", {})
    result = {}
    for key, info in presets.items():
        result[key] = {
            "name": info.get("name", key),
            "description": info.get("description", ""),
        }
    # 确保至少返回标准预设
    if "standard" not in result:
        result["standard"] = {"name": "标准分析", "description": "默认的结构化分析报告"}
    return result


def _is_custom_provider(config, provider_key):
    """检查 provider_key 是否为自定义厂商"""
    custom = config.get("custom_providers", {})
    return provider_key in custom


def _get_provider_cfg(config, provider_key):
    """获取 provider 配置（内置+自定义合并）"""
    providers = config.get("providers", {})
    cfg = providers.get(provider_key)
    if cfg:
        return cfg
    custom = config.get("custom_providers", {})
    return custom.get(provider_key)


def call_llm(prompt, provider_key="deepseek", model=None, temperature=0.7, max_tokens=4096):
    """调用 LLM 生成文本（支持内置+自定义厂商）"""
    config = load_config()
    if not provider_key:
        provider_key = config.get("default_provider", "deepseek")
    provider_cfg = _get_provider_cfg(config, provider_key)
    if not provider_cfg:
        return {"ok": False, "error": f"未找到厂商 {provider_key}"}
    if not provider_cfg.get("api_key") and provider_key != "ollama":
        return {"ok": False, "error": f"{provider_key} 未配置 API Key"}

    provider_info = BUILTIN_PROVIDERS.get(provider_key, {})
    base_url = provider_cfg.get("base_url", provider_info.get("base_url", ""))
    model_name = model or provider_cfg.get("model", provider_info.get("default_model", ""))
    api_key = provider_cfg.get("api_key", "")

    # 自定义厂商一律走 OpenAI 兼容格式
    if _is_custom_provider(config, provider_key):
        url = base_url.rstrip("/") + "/chat/completions"
        # 如果 base_url 已经包含 /chat/completions 则不再追加
        if "/chat/completions" in base_url:
            url = base_url
        return _call_openai_compat(url, api_key, model_name, prompt, temperature, max_tokens)

    try:
        if provider_key == "deepseek":
            return _call_openai_compat(base_url + "/v1/chat/completions", api_key, model_name, prompt, temperature, max_tokens)
        elif provider_key == "openai":
            return _call_openai_compat(base_url + "/chat/completions", api_key, model_name, prompt, temperature, max_tokens)
        elif provider_key == "anthropic":
            return _call_anthropic(base_url, api_key, model_name, prompt, temperature, max_tokens)
        elif provider_key == "ollama":
            return _call_ollama(base_url, model_name, prompt, temperature, max_tokens)
        else:
            # fallback: OpenAI 兼容格式
            url = base_url.rstrip("/") + "/chat/completions"
            if "/chat/completions" in base_url:
                url = base_url
            return _call_openai_compat(url, api_key, model_name, prompt, temperature, max_tokens)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _call_openai_compat(url, api_key, model, prompt, temperature, max_tokens):
    """调用兼容 OpenAI 格式的 API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = Request(url, data=body, headers=headers)
    with urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"ok": True, "content": content}


def _call_anthropic(base_url, api_key, model, prompt, temperature, max_tokens):
    """调用 Anthropic API"""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = Request(base_url + "/v1/messages", data=body, headers=headers)
    with urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    content = result.get("content", [{}])[0].get("text", "")
    return {"ok": True, "content": content}


def _call_ollama(base_url, model, prompt, temperature, max_tokens):
    """调用本地 Ollama"""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }).encode()
    req = Request(base_url + "/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())
    return {"ok": True, "content": result.get("response", "")}


# ── 流式调用 ──


def _stream_openai_compat(url, api_key, model, prompt, temperature, max_tokens):
    """流式调用 OpenAI 兼容 API，逐个 yield 文本块"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }).encode()

    parsed = urlparse(url)
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=120)
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="ignore").strip()
            if not line or line.startswith(":"):
                continue
            if line == "data: [DONE]":
                break
            if line.startswith("data: "):
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
    finally:
        conn.close()


def call_llm_stream(prompt, provider_key="deepseek", model=None, temperature=0.3, max_tokens=4096):
    """流式调用 LLM，返回 Generator。仅支持 OpenAI 兼容厂商。"""
    config = load_config()
    if not provider_key:
        provider_key = config.get("default_provider", "deepseek")
    provider_cfg = _get_provider_cfg(config, provider_key)
    if not provider_cfg:
        yield {"ok": False, "error": f"未找到厂商 {provider_key}"}
        return
    if not provider_cfg.get("api_key") and provider_key != "ollama":
        yield {"ok": False, "error": f"{provider_key} 未配置 API Key"}
        return

    provider_info = BUILTIN_PROVIDERS.get(provider_key, {})
    base_url = provider_cfg.get("base_url", provider_info.get("base_url", ""))
    model_name = model or provider_cfg.get("model", provider_info.get("default_model", ""))
    api_key = provider_cfg.get("api_key", "")

    # OpenAI 兼容格式
    url = base_url.rstrip("/") + "/chat/completions"
    if "/chat/completions" in base_url:
        url = base_url

    try:
        for text in _stream_openai_compat(url, api_key, model_name, prompt, temperature, max_tokens):
            yield {"ok": True, "delta": text}
    except Exception as e:
        yield {"ok": False, "error": str(e)}


# ── 分析报告 Prompt 模板 ──

INDUSTRY_REPORT_PROMPT = """你是一位资深行业投资分析师。请对以下行业进行深度分析，输出结构化报告。

## 行业名称
{industry}

## 要求
1. 请基于公开信息和行业常识进行分析
2. 输出格式为 Markdown，包含以下板块：
   - **行业概况**（1-2 句话概述行业现状）
   - **核心驱动因素**（列出 3-5 个关键驱动因素）
   - **产业链结构**（简要描述上下游）
   - **关键标的**（列出 3-5 家核心公司，含简短理由）
   - **近期催化剂**（未来 3-6 个月可能的事件）
   - **风险提示**（2-3 个主要风险）
3. 语言简洁专业，数据尽量具体
4. 不构成投资建议

请开始分析。"""


# ── 日历事件生成 Prompt ──

CALENDAR_GENERATION_PROMPT = """你是一位资深的行业研究专家。请为以下行业生成 2026 年全年的投资日历事件。

## 行业名称
{industry}

## 行业简介
{description}

## 关键词
{keywords}

## 输出要求
请输出 YAML 格式的日历数据，格式如下（只输出 YAML，不要额外说明）：

```yaml
core_stocks:
  - code: "000063"          # A股6位代码，美股用后缀
    name: "公司名称"
    sector: "细分领域"
    reason: "入选理由（20字以内）"

events:
  - date: "2026-01"          # 精确日期用 "2026-01-15"，月份用 "2026-01"
    date_precision: month     # 或 day
    name: "事件名称"
    importance: 4             # 1-5, 5最重要
    type: policy/product/regulation/ipo/earnings/exhibition/technology/other
    description: "事件简要描述"
    confirmed: false          # 预期事件设为 false，已确认设为 true
    suggested_action:
      stocks: []
      action: "持有/加仓/减仓/埋伏/观望"

monitors:
  - indicator: "需要监控的风险指标"
    risk_level: high/medium
    action: "对应操作建议"
```

## 具体要求
1. 每个月至少 1-2 个事件，全年至少 15 个事件
2. 重要性 5 级的事件 3-5 个（板块级催化）
3. 日期尽量具体，已知事件用精确日期，预期事件用月份
4. 事件类型包括：政策发布、产品发布、重要会议、财报、IPO、技术突破等
5. 如果这个行业很新或很小众，可以合理推断可能的事件节点
6. core_stocks 至少列出 3-5 只核心标的，包含 A 股代码（6位）或美股代码
7. 至少包含 2-3 个风险监控指标
8. 所有输出必须是合法的 YAML 格式
"""


# ── 内置示例报告（无 API Key 时展示） ──

MOCK_INDUSTRY_REPORT = """### 行业概况
光伏行业当前处于产能出清与技术迭代并行期。2025年全球光伏新增装机预计达600GW，中国占比超50%，但全产业链产能过剩导致价格战持续，行业整体利润率承压。

### 核心驱动因素
1. **全球能源转型加速** — 巴黎协定目标倒逼各国提高可再生能源占比，光伏发电成本已低于煤电，经济性驱动装机需求持续增长
2. **技术迭代（TOPCon/HJT/BC）** — N型电池技术快速取代PERC，TOPCon 2025年市占率预计超70%，BC电池在分布式场景渗透率提升
3. **电网消纳与储能配套** — 特高压建设+新型储能政策推动"光伏+储能"模式，缓解弃光率问题
4. **国际贸易壁垒** — 美国反规避、欧盟碳边境调节机制影响出口格局，东南亚产能布局成为龙头标配
5. **产能出清节奏** — 2024-2025年行业亏损加速落后产能退出，龙头市占率提升，行业集中度（CR5）有望从45%提升至60%

### 产业链结构
上游（硅料/硅片）→ 中游（电池片/组件）→ 下游（逆变器/电站运营/储能）。当前利润分布：上游硅料环节盈利触底，中游组件环节亏损面扩大，下游电站受益于组件降价IRR提升，逆变器环节受益于海外需求增长。

### 关键标的
- **隆基绿能（601012）** — BC电池技术领先，分布式渠道优势显著，资金储备充足穿越周期
- **阳光电源（300274）** — 逆变器全球份额第一，储能系统集成业务高速增长
- **晶科能源（688223）** — N型TOPCon出货量全球第一，海外产能布局领先
- **通威股份（600438）** — 硅料+电池双龙头，成本优势明显，行业出清后充分受益
- **迈为股份（300751）** — HJT整线设备龙头，受益于下一代技术路线投资

### 近期催化剂
- **2026年Q2** — 工信部新一轮《光伏制造行业规范条件》发布，有望进一步提高准入门槛，加速落后产能退出
- **2026年年中** — 美国对东南亚光伏关税豁免到期后政策明朗化
- **2026年下半年** — 国内十四五规划收官年抢装效应显现
- **欧洲夏季能源高峰** — 能源安全议题拉升海外订单预期

### 风险提示
1. 产能出清速度不及预期，行业亏损持续时间超预期
2. 海外贸易壁垒升级，关税成本侵蚀企业利润
3. 技术路线切换风险（钙钛矿等下一代技术对现有产能的颠覆）

---
> ⚠️ *此为内置示例报告。要生成真实行业分析，请在[设置页面](/settings)中配置大模型 API Key 并启用至少一个厂商。*"""


def generate_industry_report(industry, provider_key=None, model=None, extra_instructions="", force_refresh=False, custom_prompt=None):
    """生成行业分析报告（带缓存）"""
    if provider_key is None:
        config = load_config()
        provider_key = config.get("default_provider", "deepseek")

    # 检查缓存（仅在不使用自定义 prompt 时生效）
    if not custom_prompt and not force_refresh:
        key = _cache_key(industry, provider_key, extra_instructions)
        cached = _get_cached(key)
        if cached:
            return {"ok": True, "content": cached, "cached": True}

    if custom_prompt:
        prompt = custom_prompt.format(industry=industry)
    else:
        prompt = INDUSTRY_REPORT_PROMPT.format(industry=industry)
    if extra_instructions:
        prompt += f"\n\n## 额外关注点\n{extra_instructions}"
    result = call_llm(prompt, provider_key=provider_key, model=model, temperature=0.3, max_tokens=4096)

    if result.get("ok") and not custom_prompt:
        _save_cache(_cache_key(industry, provider_key, extra_instructions),
                     result["content"], industry, provider_key, extra_instructions)
    return result


def generate_calendar_events(industry_name, description="", keywords=None, provider_key=None, model=None, extra_instructions="", force_refresh=False, custom_prompt=None):
    """生成行业日历事件（带缓存）"""
    if provider_key is None:
        config = load_config()
        provider_key = config.get("default_provider", "deepseek")

    kw_str = "、".join(keywords) if keywords else "无"

    if custom_prompt:
        prompt = custom_prompt.format(
            industry=industry_name,
            description=description or f"{industry_name}行业",
            keywords=kw_str,
        )
    else:
        prompt = CALENDAR_GENERATION_PROMPT.format(
            industry=industry_name,
            description=description or f"{industry_name}行业",
            keywords=kw_str,
        )
    if extra_instructions:
        prompt += f"\n\n## 额外关注点\n{extra_instructions}"

    # 检查缓存（仅在不使用自定义 prompt 时生效）
    if not custom_prompt and not force_refresh:
        key = _cache_key(industry_name, provider_key, extra_instructions)
        cached = _get_cached(key)
        if cached:
            try:
                yaml_match = re.search(r"```(?:yaml)?\s*\n(.*?)```", cached, re.DOTALL)
                yaml_str = yaml_match.group(1) if yaml_match else cached
                parsed = yaml.safe_load(yaml_str)
                if parsed and "events" in parsed:
                    return {"ok": True, "content": parsed, "raw": cached, "cached": True}
            except Exception:
                pass

    result = call_llm(prompt, provider_key=provider_key, model=model, temperature=0.4, max_tokens=8192)

    if not result.get("ok"):
        return result

    # 尝试从返回中提取 YAML
    content = result["content"]
    yaml_match = re.search(r"```(?:yaml)?\s*\n(.*?)```", content, re.DOTALL)
    if yaml_match:
        yaml_str = yaml_match.group(1)
    else:
        yaml_str = content

    try:
        parsed = yaml.safe_load(yaml_str)
        if parsed and "events" in parsed:
            if not custom_prompt:
                _save_cache(_cache_key(industry_name, provider_key, extra_instructions),
                             content, industry_name, provider_key, extra_instructions)
            return {"ok": True, "content": parsed, "raw": content}
        else:
            return {"ok": True, "content": {"events": [], "monitors": []}, "raw": content,
                    "warning": "LLM 返回格式异常，请检查生成结果"}
    except Exception as e:
        return {"ok": False, "error": f"YAML 解析失败: {e}", "raw": content}


# ── 新闻素材推理审核 ──

MATERIALS_REVIEW_PROMPT = """你是一位行业研究分析师，负责审核新闻素材并判断哪些应该纳入投资日历。

## 行业
{industry}

## 当前日历事件
{existing_events}

## 待审核新闻素材
{materials}

## 审核要求
对每一条素材，判断它是否值得作为行业催化事件加入日历：

**值得加入的情况：**
- 有明确时间节点的行业政策/法规出台
- 重要行业会议/展览（有具体日期）
- 技术标准突破/产品发布
- 龙头公司的重大业务进展
- 行业级的供需变化信号

**不值得加入的情况：**
- 股价波动、个股新闻（非行业级）
- 券商研报观点（不是事件本身）
- 日常商品报价、常规财报
- 没有明确时间节点或时间已过的新闻
- 标题党、市场传闻

## 输出格式
只输出 YAML，不要额外说明：
```yaml
suggestions:
  - material_id: "mat_xxx"
    action: "add"              # add 或 skip
    reasoning: "具体理由（30字内）"
    event:
      date: "2026-09"          # 精确日期用 "2026-09-15"
      date_precision: "month"  # 或 "day"
      name: "事件名称"
      importance: 4            # 1-5
      type: "policy"           # policy/product/technology/exhibition/regulation/other
      description: "事件简要说明（20字内）"
      confirmed: true          # 有确切日期和来源设为 true
"""


def review_materials(industry_name, materials, existing_events, provider_key=None, model=None):
    """审核新闻素材，返回结构化建议"""
    if not materials:
        return {"ok": True, "suggestions": [], "total": 0}

    if provider_key is None:
        config = load_config()
        provider_key = config.get("default_provider", "deepseek")

    # 格式化现有日历
    if existing_events:
        ev_lines = []
        for i, ev in enumerate(existing_events, 1):
            stars = "★" * ev.get("importance", 0)
            date_str = ev.get("date", "未知日期")[:10]
            status = "✓" if ev.get("confirmed") else "~"
            ev_lines.append(f"  {i}. [{status}] {date_str} {stars} {ev.get('name', '')}")
        existing_str = "\n".join(ev_lines)
    else:
        existing_str = "  （无现有事件）"

    # 格式化素材
    mat_lines = []
    for i, m in enumerate(materials, 1):
        mat_lines.append(f"  {i}. [{m.get('source_name', '未知来源')}] {m['title']}")
        if m.get("summary"):
            mat_lines.append(f"     摘要: {m['summary'][:100]}")
        mat_lines.append(f"     链接: {m.get('source_url', '')}")
    materials_str = "\n".join(mat_lines)

    prompt = MATERIALS_REVIEW_PROMPT.format(
        industry=industry_name,
        existing_events=existing_str,
        materials=materials_str,
    )

    result = call_llm(prompt, provider_key=provider_key, model=model, temperature=0.3, max_tokens=4096)
    if not result.get("ok"):
        return result

    # 解析 YAML
    content = result["content"]
    yaml_match = re.search(r"```(?:yaml)?\s*\n(.*?)```", content, re.DOTALL)
    yaml_str = yaml_match.group(1) if yaml_match else content

    try:
        parsed = yaml.safe_load(yaml_str)
        suggestions = (parsed or {}).get("suggestions", [])
        # 只返回 action 为 add 的建议
        adds = [s for s in suggestions if s.get("action") == "add"]
        return {"ok": True, "suggestions": adds, "total": len(adds), "raw": content}
    except Exception as e:
        return {"ok": False, "error": f"解析建议失败: {e}", "raw": content}
