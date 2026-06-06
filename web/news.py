"""行业新闻抓取模块 — 多源可配置 + 技能系统"""

import json
import os
import re
import time
from datetime import datetime, date
from urllib.request import urlopen, Request

import yaml

import skills

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_FILE = os.path.join(BASE_DIR, "data", "sources.yaml")
AUTO_EVENTS_FILE = os.path.join(BASE_DIR, "data", "auto-events.yaml")

# 新闻缓存
_cache = {"data": [], "timestamp": 0}

# 关键词通过 skills 模块动态获取（内置行业 + 自定义技能）
def get_all_keywords():
    return skills.get_all_keywords()


# ── 新闻源管理 ──

def load_sources():
    """加载新闻源配置"""
    if not os.path.exists(SOURCES_FILE):
        return []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", [])


def save_sources(sources):
    """保存新闻源配置"""
    os.makedirs(os.path.dirname(SOURCES_FILE), exist_ok=True)
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        yaml.dump({"sources": sources}, f, allow_unicode=True, sort_keys=False)


def add_source(name, url, source_type="json", encoding="utf-8", fields=None):
    """添加新闻源"""
    sources = load_sources()
    new_id = f"src_{int(time.time())}"
    entry = {
        "id": new_id,
        "name": name,
        "url": url,
        "type": source_type,
        "encoding": encoding,
        "enabled": True,
        "interval": 1800,
    }
    if fields:
        entry["fields"] = {k: v for k, v in fields.items() if v}
    if source_type == "json" and fields and fields.get("items_path"):
        entry["items_path"] = fields["items_path"]
    sources.append(entry)
    save_sources(sources)
    return new_id


def remove_source(src_id):
    """删除新闻源"""
    sources = load_sources()
    sources = [s for s in sources if s["id"] != src_id]
    save_sources(sources)


def toggle_source(src_id, enabled=None):
    """启/禁用新闻源"""
    sources = load_sources()
    for s in sources:
        if s["id"] == src_id:
            if enabled is None:
                s["enabled"] = not s.get("enabled", True)
            else:
                s["enabled"] = enabled
            break
    save_sources(sources)


# ── 新闻抓取 ──

def fetch_from_source(source):
    """从单个源抓取新闻"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        req = Request(source["url"], headers=headers)
        encoding = source.get("encoding", "utf-8")
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode(encoding, errors="ignore")

        stype = source.get("type", "json")
        if stype == "json":
            return _parse_json_response(raw, source)
        elif stype == "rss":
            return _parse_rss_response(raw, source)
        return []
    except Exception as e:
        print(f"[新闻] {source.get('name','未知')} 抓取失败: {e}")
        return []


def _parse_json_response(raw, source):
    """解析 JSON 格式的新闻响应"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    # 按路径提取列表
    items_path = source.get("items_path", "")
    if items_path:
        parts = items_path.split(".")
        items = data
        for p in parts:
            items = items.get(p, {}) if isinstance(items, dict) else []
    else:
        items = data

    if not isinstance(items, list):
        return []

    fields = source.get("fields", {})
    title_key = fields.get("title", "title")
    summary_key = fields.get("summary", "intro")
    time_key = fields.get("time", "ctime")
    url_key = fields.get("url", "url")

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # 尝试多个可能的标题字段
        title = ""
        for possible_key in [title_key, "title", "Title", "name", "Name", "content"]:
            val = item.get(possible_key)
            if val and isinstance(val, str) and len(val) > 2:
                title = val
                break
        if not title:
            continue

        # 行业关键词匹配
        text = title + (item.get(summary_key, "") or "")
        matched = []
        for ind, keywords in get_all_keywords().items():
            for kw in keywords:
                if kw in text:
                    matched.append(ind)
                    break

        # 时间解析
        raw_time = item.get(time_key, "")
        time_str = _parse_time(raw_time)

        result.append({
            "title": title,
            "intro": (item.get(summary_key, "") or "")[:200],
            "time": time_str,
            "url": item.get(url_key, ""),
            "source": source.get("name", "未知"),
            "industries": matched,
            "matched": len(matched) > 0,
        })
    return result


def _parse_rss_response(raw, source):
    """简易 RSS 解析"""
    result = []
    # 简单提取 <item> 标签
    items = re.findall(r"<item>(.*?)</item>", raw, re.DOTALL)
    for item_xml in items:
        title = _extract_xml_tag(item_xml, "title")
        if not title:
            continue
        desc = _extract_xml_tag(item_xml, "description")
        link = _extract_xml_tag(item_xml, "link")
        pub_date = _extract_xml_tag(item_xml, "pubDate")

        text = title + (desc or "")
        matched = []
        for ind, keywords in get_all_keywords().items():
            for kw in keywords:
                if kw in text:
                    matched.append(ind)
                    break

        result.append({
            "title": title,
            "intro": (desc or "")[:200],
            "time": pub_date[:16] if pub_date else "",
            "url": link or "",
            "source": source.get("name", "未知"),
            "industries": matched,
            "matched": len(matched) > 0,
        })
    return result


def _extract_xml_tag(xml, tag):
    m = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", xml, re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_time(raw):
    """解析多种时间格式"""
    if not raw:
        return ""
    # Unix timestamp (string or int)
    try:
        ts = int(raw)
        if ts > 1000000000:  # 合理的时间戳范围
            return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        pass
    # 尝试常见格式
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S"]:
        try:
            return datetime.strptime(str(raw)[:19], fmt).strftime("%m-%d %H:%M")
        except (ValueError, IndexError):
            continue
    return str(raw)[:16]


# ── 事件自动检测 ──

def detect_events_from_news(news_items):
    """从新闻中检测可能的事件"""
    detected = []

    current_month = date.today().month
    month_names = {"1": "1月", "2": "2月", "3": "3月", "4": "4月",
                   "5": "5月", "6": "6月", "7": "7月", "8": "8月",
                   "9": "9月", "10": "10月", "11": "11月", "12": "12月"}

    for item in news_items:
        if not item["matched"] or not item["industries"]:
            continue

        title = item["title"]
        intro = item["intro"]
        text = title + " " + intro

        # 提取日期关键词
        date_match = None
        # 匹配 "X月X日" 或 "X月X-X日"
        m = re.search(r"(\d{1,2})月(\d{1,2})(?:日|号)?", text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            date_match = f"2026-{month:02d}-{day:02d}"

        if not date_match:
            continue

        # 计算置信度
        confidence = 0.5
        # 含具体日期 +0.2
        confidence += 0.2
        # 含"发布/公布/宣布/召开/举行"等动作词 +0.15
        if re.search(r"发布|公布|宣布|召开|举行|开幕|首发|发射|上线|启动", text):
            confidence += 0.15
        # 含具体数字 +0.1
        if re.search(r"\d+[%亿万千]", text):
            confidence += 0.1
        # 含提及的标的名 +0.05
        stock_names = ["中兴通讯", "亿航", "宁德时代", "比亚迪", "寒武纪", "科大讯飞",
                       "华为", "特斯拉", "英伟达", "腾讯", "阿里", "百度"]
        for sn in stock_names:
            if sn in text:
                confidence += 0.05

        confidence = min(confidence, 0.95)

        if confidence >= 0.6:
            detected.append({
                "date": date_match,
                "name": title[:80],
                "industry": item["industries"][0],
                "all_industries": item["industries"],
                "source_url": item["url"],
                "source_title": title,
                "confidence": round(confidence, 2),
                "status": "pending",
                "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    return detected


def save_detected_events(events):
    """保存检测到的事件"""
    os.makedirs(os.path.dirname(AUTO_EVENTS_FILE), exist_ok=True)
    # 合并现有 + 新检测
    existing = load_detected_events()
    existing_urls = {e["source_url"] for e in existing if e.get("source_url")}
    new_count = 0
    for ev in events:
        if ev["source_url"] not in existing_urls:
            existing.append(ev)
            existing_urls.add(ev["source_url"])
            new_count += 1
    with open(AUTO_EVENTS_FILE, "w", encoding="utf-8") as f:
        yaml.dump({"detected_events": existing}, f, allow_unicode=True, sort_keys=False)
    return new_count


def load_detected_events():
    """加载检测到的事件"""
    if not os.path.exists(AUTO_EVENTS_FILE):
        return []
    with open(AUTO_EVENTS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("detected_events", [])


def accept_event(event_idx):
    """接受检测到的事件（标记为已确认）"""
    events = load_detected_events()
    if 0 <= event_idx < len(events):
        events[event_idx]["status"] = "accepted"
        with open(AUTO_EVENTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump({"detected_events": events}, f, allow_unicode=True, sort_keys=False)
        return True
    return False


def reject_event(event_idx):
    """拒绝检测到的事件"""
    events = load_detected_events()
    if 0 <= event_idx < len(events):
        events[event_idx]["status"] = "rejected"
        with open(AUTO_EVENTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump({"detected_events": events}, f, allow_unicode=True, sort_keys=False)
        return True
    return False


# ── 缓存管理 ──

def refresh_news():
    """刷新所有启用的新闻源"""
    sources = load_sources()
    enabled_sources = [s for s in sources if s.get("enabled", True)]

    if not enabled_sources:
        print("[新闻] 没有启用的新闻源，请在设置中添加")
        _cache["data"] = []
        _cache["timestamp"] = time.time()
        return []

    all_items = []
    success_count = 0
    for src in enabled_sources:
        items = fetch_from_source(src)
        if items:
            all_items.extend(items)
            success_count += 1
        else:
            print(f"[新闻] {src.get('name','未知')} 返回空数据")

    # 去重
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # 按时间排序
    unique.sort(key=lambda x: x.get("time", ""), reverse=True)

    _cache["data"] = unique
    _cache["timestamp"] = time.time()

    matched = [n for n in unique if n["matched"]]
    print(f"[新闻] 刷新成功: {len(unique)}条 (来自 {success_count}/{len(enabled_sources)} 个源), 相关 {len(matched)}条")

    # 自动检测事件
    detected = detect_events_from_news(unique)
    if detected:
        new_count = save_detected_events(detected)
        if new_count > 0:
            print(f"[检测] 发现 {new_count} 个新事件待审核")

    return unique


def get_news(force_refresh=False):
    """获取新闻（带缓存）"""
    if force_refresh or (time.time() - _cache["timestamp"] > 300):
        return refresh_news()
    return _cache["data"]


def get_news_by_industry(industry_name):
    """获取特定行业的新闻"""
    all_news = get_news()
    return [n for n in all_news if industry_name in n.get("industries", [])]


if __name__ == "__main__":
    print("测试多源新闻抓取...")
    news = refresh_news()
    print(f"共 {len(news)} 条新闻")
    for n in news[:5]:
        tags = "[" + ",".join(n["industries"]) + "]" if n["industries"] else "[通用]"
        print(f"  {tags} {n['title'][:60]}")

    print(f"\n待审核事件: {len([e for e in load_detected_events() if e['status'] == 'pending'])}")
