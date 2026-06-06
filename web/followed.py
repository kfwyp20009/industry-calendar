"""关注行业管理 — 用户自定义侧边栏显示哪些行业"""

import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLLOWED_FILE = os.path.join(BASE_DIR, "data", "followed.json")


def _load():
    """加载关注列表"""
    if not os.path.exists(FOLLOWED_FILE):
        return None
    try:
        with open(FOLLOWED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return None


def _save(names):
    """保存关注列表"""
    os.makedirs(os.path.dirname(FOLLOWED_FILE), exist_ok=True)
    with open(FOLLOWED_FILE, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)


def init_followed(all_names):
    """首次初始化：关注所有行业。文件不存在或为空列表时都做初始化"""
    existing = _load()
    if existing:
        return existing
    # 文件不存在 或 文件内容为 [] → 自动填充所有行业
    _save(sorted(all_names))
    return sorted(all_names)


def get_followed_names():
    """获取已关注的行业名称列表"""
    names = _load()
    return names if names is not None else []


def is_followed(name):
    """检查是否已关注"""
    names = get_followed_names()
    return name in names


def follow(name):
    """关注一个行业"""
    names = get_followed_names()
    if name not in names:
        names.append(name)
        _save(names)
    return names


def unfollow(name):
    """取消关注（不删除数据）"""
    names = get_followed_names()
    if name in names:
        names.remove(name)
        _save(names)
    return names


def toggle(name):
    """切换关注状态，返回新的关注状态"""
    if is_followed(name):
        unfollow(name)
        return False
    else:
        follow(name)
        return True
