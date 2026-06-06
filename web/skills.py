"""技能系统 — 用户可自定义监控任意行业/话题"""

import os
import json
import time
from datetime import datetime

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_FILE = os.path.join(BASE_DIR, "data", "skills", "custom.yaml")

# 关联数据文件路径
ETF_MAPPING_FILE = os.path.join(BASE_DIR, "data", "etf_mapping.yaml")
CROSS_INDUSTRY_FILE = os.path.join(BASE_DIR, "data", "cross-industry.yaml")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "data", "stocks", "portfolio.yaml")
FOLLOWED_FILE = os.path.join(BASE_DIR, "data", "followed.json")

# 内置行业技能（不可删除）
BUILTIN_SKILLS = {
    "6G通信": {"keywords": ["6G", "5G-A", "通信", "中兴通讯", "IMT-2030", "3GPP"],
               "builtin": True, "description": "6G通信标准与产业"},
    "低空经济": {"keywords": ["低空经济", "eVTOL", "亿航", "无人机", "空域", "低空"],
               "builtin": True, "description": "低空经济与eVTOL"},
    "卫星互联网": {"keywords": ["卫星互联网", "千帆星座", "星链", "卫星", "铖昌", "航天电子"],
               "builtin": True, "description": "卫星互联网与星座组网"},
    "机器人零部件": {"keywords": ["机器人", "减速器", "绿的谐波", "Optimus", "人形机器人", "柯力传感"],
               "builtin": True, "description": "机器人核心零部件"},
    "具身智能": {"keywords": ["具身智能", "人形机器人", "宇树", "VLA", "优必选"],
               "builtin": True, "description": "具身智能与人形机器人"},
    "绿氢氨醇": {"keywords": ["绿氢", "氢能", "电解槽", "甲醇", "IMO", "碳税", "氨"],
               "builtin": True, "description": "绿色氢能与航运燃料"},
    "数字人民币": {"keywords": ["数字人民币", "数币", "CBDC", "mBridge", "支付", "数字货币"],
               "builtin": True, "description": "数字人民币与央行数字货币"},
    "AI大模型/应用": {"keywords": ["AI", "大模型", "人工智能", "算力", "GPT", "智谱", "千问", "豆包"],
               "builtin": True, "description": "AI大模型与应用落地"},
    "半导体/国产替代": {"keywords": ["半导体", "芯片", "光刻机", "国产替代", "HBM", "中芯", "北方华创"],
               "builtin": True, "description": "半导体产业链与国产替代"},
    "商业航天/火箭": {"keywords": ["商业航天", "火箭", "长征", "朱雀", "可回收", "蓝箭"],
               "builtin": True, "description": "商业航天与可回收火箭"},
    "自动驾驶/L4": {"keywords": ["自动驾驶", "FSD", "Robotaxi", "智驾", "域控", "德赛西威"],
               "builtin": True, "description": "自动驾驶与L4商业化"},
}


def load_custom_skills():
    """加载用户自定义技能"""
    if not os.path.exists(SKILLS_FILE):
        return [], []
    with open(SKILLS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("skills", []), data.get("hidden_builtins", [])


def _load_skills_file():
    """加载完整 custom.yaml 数据"""
    if not os.path.exists(SKILLS_FILE):
        return {"skills": [], "hidden_builtins": []}
    with open(SKILLS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_custom_skills(skills, hidden_builtins=None):
    """保存自定义技能"""
    os.makedirs(os.path.dirname(SKILLS_FILE), exist_ok=True)
    data = {"skills": skills, "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if hidden_builtins is not None:
        data["hidden_builtins"] = hidden_builtins
    else:
        # 保留现有的 hidden_builtins
        existing = _load_skills_file()
        data["hidden_builtins"] = existing.get("hidden_builtins", [])
    with open(SKILLS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def get_hidden_builtins():
    """获取被隐藏的内置技能名称列表"""
    _, hidden = load_custom_skills()
    return hidden


def get_all_skills():
    """获取所有技能（内置+自定义），返回 {名称: {keywords, builtin, ...}}"""
    hidden = get_hidden_builtins()
    result = {}
    for name, info in BUILTIN_SKILLS.items():
        if name not in hidden:
            result[name] = {**info, "builtin": True}
    for s in load_custom_skills()[0]:
        name = s["name"]
        result[name] = {
            "keywords": s.get("keywords", []),
            "builtin": False,
            "description": s.get("description", ""),
            "id": s.get("id", ""),
        }
    return result


def get_visible_builtin_skills():
    """获取可见的内置技能（排除已隐藏的）"""
    hidden = get_hidden_builtins()
    return {n: info for n, info in BUILTIN_SKILLS.items() if n not in hidden}


def get_all_keywords():
    """获取所有技能的关键词映射 {名称: [关键词列表]}"""
    mapping = {}
    for name, info in get_all_skills().items():
        mapping[name] = info["keywords"]
    return mapping


def normalize_keywords(keywords):
    """统一关键词分割：支持英文逗号、中文逗号、中文顿号"""
    if isinstance(keywords, str):
        keywords = [keywords]
    result = []
    for kw in keywords:
        for sep in [",", "，", "、", ";", "；"]:
            kw = kw.replace(sep, ",")
        for part in kw.split(","):
            part = part.strip()
            if part:
                result.append(part)
    return result


def add_skill(name, keywords, description=""):
    """添加自定义技能"""
    skills, hidden = load_custom_skills()

    # 检查名称是否已存在
    for s in skills:
        if s["name"] == name:
            return False, "同名技能已存在"

    if name in BUILTIN_SKILLS:
        return False, "该名称与内置技能冲突"

    skills.append({
        "id": f"skill_{int(time.time())}",
        "name": name,
        "keywords": normalize_keywords(keywords),
        "description": description,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_custom_skills(skills, hidden)
    return True, "添加成功"


def update_skill(skill_id, name=None, keywords=None, description=None):
    """更新自定义技能"""
    skills, hidden = load_custom_skills()
    for s in skills:
        if s.get("id") == skill_id:
            if name:
                s["name"] = name
            if keywords is not None:
                s["keywords"] = normalize_keywords(keywords)
            if description is not None:
                s["description"] = description
            save_custom_skills(skills, hidden)
            return True, "更新成功"
    return False, "未找到该技能"


def delete_skill(skill_id):
    """删除自定义技能（同时清理关联的行业文件）"""
    skills, hidden = load_custom_skills()
    deleted_skill = None
    for s in skills:
        if s.get("id") == skill_id:
            deleted_skill = s
            break
    skills = [s for s in skills if s.get("id") != skill_id]
    save_custom_skills(skills, hidden)
    # 同时清理关联的行业文件
    if deleted_skill:
        remove_industry_file(deleted_skill["name"])
    return True, "删除成功"


def hide_builtin_skill(name):
    """隐藏一个内置技能"""
    if name not in BUILTIN_SKILLS:
        return False, "不是内置技能"
    skills, hidden = load_custom_skills()
    if name not in hidden:
        hidden.append(name)
    save_custom_skills(skills, hidden)
    return True, "已隐藏"


def restore_builtin_skill(name):
    """恢复一个被隐藏的内置技能"""
    skills, hidden = load_custom_skills()
    if name in hidden:
        hidden.remove(name)
    save_custom_skills(skills, hidden)
    return True, "已恢复"


# ── 技能 ↔ 行业转换 ──

INDUSTRIES_DIR = os.path.join(BASE_DIR, "data", "industries")
CONFIG_FILE = os.path.join(BASE_DIR, "data", "config.yaml")


def _safe_filename(name):
    """从行业名生成安全的文件名"""
    safe = name.replace("/", "·").replace("\\", "·")
    safe = "".join(c for c in safe if c.isascii() or c in "·- " or not c.isascii())
    return safe


def _get_next_industry_id():
    """获取下一个可用的行业编号"""
    if not os.path.isdir(INDUSTRIES_DIR):
        return 12
    max_id = 0
    for fname in os.listdir(INDUSTRIES_DIR):
        if fname.endswith(".yaml") and fname[:2].isdigit():
            try:
                max_id = max(max_id, int(fname[:2]))
            except ValueError:
                continue
    return max_id + 1


def create_industry_file(name, keywords, description=""):
    """从技能创建行业数据文件"""
    os.makedirs(INDUSTRIES_DIR, exist_ok=True)

    # 检查是否已存在同名行业
    for fname in os.listdir(INDUSTRIES_DIR):
        if fname.endswith(".yaml"):
            fpath = os.path.join(INDUSTRIES_DIR, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f) or {}
                    if data.get("industry") == name:
                        return False, f"行业 '{name}' 已存在 (文件: {fname})", None
                except Exception:
                    continue

    next_id = _get_next_industry_id()
    safe_name = _safe_filename(name)
    fname = f"{next_id:02d}-{safe_name}.yaml"
    fpath = os.path.join(INDUSTRIES_DIR, fname)

    # 过滤出适合作为标签的关键词（2-8个字符的短词）
    tags = [kw for kw in keywords if 2 <= len(kw) <= 8][:5]
    if not tags:
        tags = ["新兴", "科技"]

    industry_data = {
        "industry": name,
        "description": description or f"自定义行业：{name}（基于技能自动创建）",
        "tags": tags,
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "core_stocks": [],
        "events": [],
        "monitors": [],
    }

    with open(fpath, "w", encoding="utf-8") as f:
        yaml.dump(industry_data, f, allow_unicode=True, sort_keys=False)

    # 更新 config.yaml
    _update_config_industries(name, tags, next_id)

    return True, f"行业文件已创建: {fname}", fname


def _update_config_industries(name, tags, industry_id):
    """将新行业添加到 config.yaml"""
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        config = {}

    industries = config.get("industries", [])
    # 检查是否已存在
    for ind in industries:
        if ind.get("name") == name:
            return

    industries.append({
        "id": f"{industry_id:02d}",
        "name": name,
        "enabled": True,
        "tags": tags,
    })
    config["industries"] = industries
    config["project"]["updated"] = datetime.now().strftime("%Y-%m-%d")

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)


def remove_industry_file(name):
    """删除行业数据文件（从文件系统和config.yaml）"""
    # 删除文件
    if os.path.isdir(INDUSTRIES_DIR):
        for fname in os.listdir(INDUSTRIES_DIR):
            if fname.endswith(".yaml"):
                fpath = os.path.join(INDUSTRIES_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    if data.get("industry") == name:
                        os.remove(fpath)
                        break
                except Exception:
                    continue

    # 从 config.yaml 移除
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            industries = config.get("industries", [])
            config["industries"] = [i for i in industries if i.get("name") != name]
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, sort_keys=False)
        except Exception:
            pass


def is_custom_skill_industry(name):
    """判断一个行业名是否来自自定义技能（而非内置行业）"""
    for s in load_custom_skills()[0]:
        if s["name"] == name:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# 行业关联数据同步（新增/删除行业时同步更新以下文件）
# ═══════════════════════════════════════════════════════════════

def _load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def sync_etf_mapping(industry_name, etf_code="", etf_name=""):
    """新增行业时同步 ETF 映射（提供代码则写入，否则留占位）"""
    data = _load_yaml(ETF_MAPPING_FILE)
    mapping = data.setdefault("mapping", {})
    if industry_name not in mapping:
        note = ""
        if not etf_code:
            note = f"自定义行业：{industry_name}（请核实并填入ETF代码）"
        elif not etf_name:
            etf_name = f"{industry_name}ETF"
        mapping[industry_name] = {
            "code": etf_code,
            "name": etf_name,
            "exchange": "SH",
            "type": "自定义",
            "note": note,
        }
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_yaml(ETF_MAPPING_FILE, data)


def remove_from_etf_mapping(industry_name):
    """删除行业时清理 ETF 映射"""
    data = _load_yaml(ETF_MAPPING_FILE)
    if industry_name in data.get("mapping", {}):
        del data["mapping"][industry_name]
        data["updated"] = datetime.now().strftime("%Y-%m-%d")
        _save_yaml(ETF_MAPPING_FILE, data)


def sync_cross_industry(industry_name, tags=None):
    """新增行业时同步跨行业联动（添加空关联矩阵行）"""
    data = _load_yaml(CROSS_INDUSTRY_FILE)
    affinity = data.setdefault("affinity_matrix", {})
    if industry_name not in affinity:
        affinity[industry_name] = {}
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_yaml(CROSS_INDUSTRY_FILE, data)


def remove_from_cross_industry(industry_name):
    """删除行业时从联动数据清理（矩阵行/列 + 联动事件）"""
    data = _load_yaml(CROSS_INDUSTRY_FILE)
    # 删除该行业的矩阵行
    if industry_name in data.get("affinity_matrix", {}):
        del data["affinity_matrix"][industry_name]
    # 从其他行业的矩阵行中删除对该行业的引用
    for row_name in list(data.get("affinity_matrix", {})):
        if industry_name in data["affinity_matrix"][row_name]:
            del data["affinity_matrix"][row_name][industry_name]
    # 删除包含该行业的联动事件
    if "cross_events" in data:
        data["cross_events"] = [
            e for e in data["cross_events"]
            if industry_name not in e.get("industries", [])
        ]
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_yaml(CROSS_INDUSTRY_FILE, data)


def remove_from_portfolio(industry_name):
    """删除行业时清理组合池中该行业的标的"""
    data = _load_yaml(PORTFOLIO_FILE)
    if "stocks" in data:
        old_len = len(data["stocks"])
        data["stocks"] = [s for s in data["stocks"] if s.get("industry") != industry_name]
        if len(data["stocks"]) != old_len:
            data["updated"] = datetime.now().strftime("%Y-%m-%d")
            _save_yaml(PORTFOLIO_FILE, data)


def remove_from_followed(industry_name):
    """删除行业时取消关注"""
    try:
        if not os.path.exists(FOLLOWED_FILE):
            return
        with open(FOLLOWED_FILE, "r", encoding="utf-8") as f:
            names = json.load(f)
        if isinstance(names, list) and industry_name in names:
            names.remove(industry_name)
            with open(FOLLOWED_FILE, "w", encoding="utf-8") as f:
                json.dump(names, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


