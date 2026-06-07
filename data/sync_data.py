"""数据同步模块

以 data/industries/*.yaml 为唯一事实来源，自动同步以下派生数据：
- data/stocks/portfolio.yaml（合并 core_stocks，支持一股多行业）
- data/config.yaml（industries 列表）
- data/cross-industry.yaml（affinity_matrix 行列）
- data/etf_mapping.yaml（行业映射条目）
"""

import os
import yaml
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDUSTRIES_DIR = os.path.join(BASE_DIR, "data", "industries")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "data", "stocks", "portfolio.yaml")
CONFIG_FILE = os.path.join(BASE_DIR, "data", "config.yaml")
CROSS_FILE = os.path.join(BASE_DIR, "data", "cross-industry.yaml")
ETF_FILE = os.path.join(BASE_DIR, "data", "etf_mapping.yaml")


def _load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def discover_industries():
    """扫描文件系统发现所有行业（含 core_stocks），返回 {name: data}"""
    industries = {}
    if not os.path.isdir(INDUSTRIES_DIR):
        return industries
    for fname in sorted(os.listdir(INDUSTRIES_DIR)):
        if not fname.endswith(".yaml"):
            continue
        data = _load_yaml(os.path.join(INDUSTRIES_DIR, fname))
        if data and "industry" in data:
            industries[data["industry"]] = data
    return industries


def build_portfolio_data(industries):
    """从所有行业的 core_stocks 合并成统一标的池（一股多行业）

    返回格式：
    {
        "stocks": [{
            "code": "601012",
            "name": "隆基绿能",
            "industries": ["绿氢氨醇", "绿色能源"],
            "market": "A股",
            "estimated_pe": "15-20x",
            "key_dates": ["月度招标(每月)", "H1出货(7月)", "十五五规划(11月)"],
        }]
    }
    """
    merged = {}
    for ind_name, ind_data in industries.items():
        for stock in ind_data.get("core_stocks", []):
            code = stock.get("code", "")
            if not code:
                continue
            if code not in merged:
                merged[code] = {
                    "code": code,
                    "name": stock.get("name", ""),
                    "industries": [],
                    "market": stock.get("market", "A股"),
                    "estimated_pe": stock.get("estimated_pe", ""),
                    "key_dates": list(stock.get("key_dates", [])),
                }
            else:
                existing_dates = set(merged[code]["key_dates"])
                for d in stock.get("key_dates", []):
                    if d not in existing_dates:
                        merged[code]["key_dates"].append(d)
                        existing_dates.add(d)
            merged[code]["industries"].append(ind_name)

    stocks = list(merged.values())
    stocks.sort(key=lambda s: s["code"])
    return {
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "_generated": True,
        "_note": "自动生成，请勿手动编辑。修改标的请编辑 data/industries/*.yaml 中的 core_stocks",
        "stocks": stocks,
    }


def sync_portfolio(industries=None):
    """重新生成 portfolio.yaml"""
    if industries is None:
        industries = discover_industries()
    portfolio = build_portfolio_data(industries)
    _save_yaml(PORTFOLIO_FILE, portfolio)
    return portfolio


def sync_config(industries=None):
    """同步 config.yaml —— 确保 industries 列表与文件系统一致"""
    if industries is None:
        industries = discover_industries()
    config = _load_yaml(CONFIG_FILE)
    if not config:
        return

    now = datetime.now().strftime("%Y-%m-%d")
    existing = {ind.get("name") for ind in config.get("industries", [])}

    for name, data in industries.items():
        if name not in existing:
            tags = data.get("tags", [])[:5]
            config["industries"].append({
                "name": name,
                "enabled": True,
                "tags": tags,
            })

    config["project"]["updated"] = now
    _save_yaml(CONFIG_FILE, config)


def sync_cross_industry(industries=None):
    """同步 cross-industry.yaml —— 确保所有行业在 affinity_matrix 中有行"""
    if industries is None:
        industries = discover_industries()
    cross = _load_yaml(CROSS_FILE)
    if not cross:
        cross = {"affinity_matrix": {}, "cross_events": []}

    affinity = cross.setdefault("affinity_matrix", {})
    for name in industries:
        if name not in affinity:
            affinity[name] = {}
    # 清理已删除行业的残留行
    for name in list(affinity.keys()):
        if name not in industries:
            del affinity[name]
    # 清理已删除行业的残留列
    for row_name in list(affinity.keys()):
        for col_name in list(affinity[row_name].keys()):
            if col_name not in industries:
                del affinity[row_name][col_name]

    cross["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_yaml(CROSS_FILE, cross)


def sync_etf_mapping(industries=None):
    """同步 etf_mapping.yaml —— 确保所有行业有映射条目"""
    if industries is None:
        industries = discover_industries()
    etf = _load_yaml(ETF_FILE)
    if not etf:
        etf = {"mapping": {}}

    mapping = etf.setdefault("mapping", {})
    for name in industries:
        if name not in mapping:
            mapping[name] = {
                "code": "",
                "name": "",
                "exchange": "SH",
                "type": "自定义",
                "note": f"自动添加：{name}（请核实并填入ETF代码）",
            }
    # 清理已删除行业的残留条目
    for name in list(mapping.keys()):
        if name not in industries:
            del mapping[name]

    etf["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_yaml(ETF_FILE, etf)


def sync_all():
    """全量同步：行业 YAML → 所有派生数据"""
    industries = discover_industries()
    portfolio = sync_portfolio(industries)
    sync_config(industries)
    sync_cross_industry(industries)
    sync_etf_mapping(industries)
    return {
        "ok": True,
        "message": f"同步完成: {len(industries)} 个行业, {len(portfolio.get('stocks', []))} 只标的",
    }


if __name__ == "__main__":
    result = sync_all()
    print(result["message"])
