"""LLM 多厂商接入模块 — 支持 DeepSeek / OpenAI / Anthropic / Ollama"""

import os
import json
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "llm_config.yaml")

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
    "ollama": {
        "name": "Ollama (本地)",
        "base_url": "http://localhost:11434",
        "models": ["llama3", "qwen2.5", "deepseek-r1"],
        "default_model": "qwen2.5",
        "docs_url": None,
    },
}


def load_config():
    """加载 LLM 配置"""
    if not os.path.exists(CONFIG_FILE):
        return _default_config()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


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


def get_enabled_providers():
    """获取已启用的厂商列表"""
    config = load_config()
    providers = config.get("providers", {})
    return [(key, info) for key, info in providers.items() if info.get("enabled")]


def call_llm(prompt, provider_key="deepseek", model=None, temperature=0.7, max_tokens=4096):
    """调用 LLM 生成文本"""
    config = load_config()
    providers = config.get("providers", {})
    provider_cfg = providers.get(provider_key)
    if not provider_cfg:
        return {"ok": False, "error": f"未找到厂商 {provider_key}"}
    if not provider_cfg.get("api_key") and provider_key != "ollama":
        return {"ok": False, "error": f"{provider_key} 未配置 API Key"}

    provider_info = BUILTIN_PROVIDERS.get(provider_key, {})
    base_url = provider_cfg.get("base_url", provider_info.get("base_url", ""))
    model_name = model or provider_cfg.get("model", provider_info.get("default_model", ""))
    api_key = provider_cfg.get("api_key", "")

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
            return {"ok": False, "error": f"不支持的厂商: {provider_key}"}
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


def generate_industry_report(industry, provider_key=None, model=None):
    """生成行业分析报告"""
    if provider_key is None:
        config = load_config()
        provider_key = config.get("default_provider", "deepseek")

    prompt = INDUSTRY_REPORT_PROMPT.format(industry=industry)
    return call_llm(prompt, provider_key=provider_key, model=model, temperature=0.3, max_tokens=4096)


def generate_calendar_events(industry_name, description="", keywords=None, provider_key=None, model=None):
    """生成行业日历事件"""
    if provider_key is None:
        config = load_config()
        provider_key = config.get("default_provider", "deepseek")

    kw_str = "、".join(keywords) if keywords else "无"
    prompt = CALENDAR_GENERATION_PROMPT.format(
        industry=industry_name,
        description=description or f"{industry_name}行业",
        keywords=kw_str,
    )
    result = call_llm(prompt, provider_key=provider_key, model=model, temperature=0.4, max_tokens=8192)

    if not result.get("ok"):
        return result

    # 尝试从返回中提取 YAML
    content = result["content"]
    import re
    yaml_match = re.search(r"```(?:yaml)?\s*\n(.*?)```", content, re.DOTALL)
    if yaml_match:
        yaml_str = yaml_match.group(1)
    else:
        yaml_str = content

    try:
        import yaml as yaml_lib
        parsed = yaml_lib.safe_load(yaml_str)
        if parsed and "events" in parsed:
            return {"ok": True, "content": parsed, "raw": content}
        else:
            return {"ok": True, "content": {"events": [], "monitors": []}, "raw": content,
                    "warning": "LLM 返回格式异常，请检查生成结果"}
    except Exception as e:
        return {"ok": False, "error": f"YAML 解析失败: {e}", "raw": content}
