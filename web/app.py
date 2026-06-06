"""行业投资日历系统 — 本地 Web 应用"""

import os
import sys
from collections import defaultdict
from datetime import datetime, date

import yaml
from flask import Flask, render_template, abort, jsonify, request
import news
import skills
import llm
import followed

app = Flask(__name__)

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "industries")
CROSS_FILE = os.path.join(BASE_DIR, "data", "cross-industry.yaml")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "data", "stocks", "portfolio.yaml")
ETF_FILE = os.path.join(BASE_DIR, "data", "etf_mapping.yaml")

# ── 数据加载 ──
def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_all_industries():
    """加载所有行业数据"""
    industries = {}
    if not os.path.isdir(DATA_DIR):
        return industries
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith(".yaml"):
            data = load_yaml(os.path.join(DATA_DIR, fname))
            if data and "industry" in data:
                code = fname.replace(".yaml", "")
                data["_code"] = code
                data["_file"] = fname
                # 标记当月事件
                now = date.today()
                month_str = f"{now.year}-{now.month:02d}"
                for ev in data.get("events", []):
                    ev_date = ev.get("date", "")
                    ev["is_current_month"] = ev_date.startswith(month_str) if ev_date else False
                industries[code] = data
    return industries


def get_current_month_events(industries):
    """聚合当月所有行业事件"""
    now = date.today()
    month_str = f"{now.year}-{now.month}"
    events = []
    for code, ind in industries.items():
        for ev in ind.get("events", []):
            if ev.get("is_current_month"):
                events.append({
                    **ev,
                    "industry": ind["industry"],
                    "industry_code": code,
                })
    # 按日期排序
    events.sort(key=lambda e: e.get("date", ""))
    return events


def get_upcoming_events(industries, days=14):
    """获取未来 N 天事件"""
    now = date.today()
    events = []
    for code, ind in industries.items():
        for ev in ind.get("events", []):
            ev_date_str = ev.get("date", "")
            try:
                ev_date = datetime.strptime(ev_date_str[:10], "%Y-%m-%d").date()
                if now <= ev_date <= date(now.year, now.month, now.day + days):
                    events.append({
                        **ev,
                        "industry": ind["industry"],
                        "industry_code": code,
                        "days_left": (ev_date - now).days,
                    })
            except (ValueError, IndexError):
                continue
    events.sort(key=lambda e: e.get("date", ""))
    return events


def get_importance_color(imp):
    return {5: "#dc3545", 4: "#fd7e14", 3: "#ffc107", 2: "#6c757d", 1: "#adb5bd"}.get(imp, "#6c757d")


def get_importance_label(imp):
    return {5: "★★★★★", 4: "★★★★", 3: "★★★", 2: "★★", 1: "★"}.get(imp, "")


def get_action_color(action):
    colors = {
        "加仓": "#dc3545",
        "建仓": "#dc3545",
        "埋伏": "#fd7e14",
        "波段": "#fd7e14",
        "持有": "#28a745",
        "观望": "#6c757d",
        "减仓": "#17a2b8",
        "清仓": "#343a40",
    }
    return colors.get(action, "#6c757d")


def get_stock_url(code):
    """根据股票代码生成雪球链接"""
    if not code:
        return "#"
    if code.endswith(".US"):
        return f"https://xueqiu.com/S/{code.replace('.US','')}"
    if code.startswith("6"):
        return f"https://xueqiu.com/S/SH{code}"
    if code.startswith(("0", "3")):
        return f"https://xueqiu.com/S/SZ{code}"
    return f"https://xueqiu.com/S/{code}"


# ── 全局上下文 ──
@app.context_processor
def inject_globals():
    all_industries = load_all_industries()
    all_names = {ind["industry"] for ind in all_industries.values()}
    followed_names = followed.init_followed(all_names)
    return dict(
        industries=all_industries,
        now=date.today(),
        llm=llm,
        llm_config=llm.load_config(),
        followed_names=followed_names,
        is_followed=followed.is_followed,
        get_stock_url=get_stock_url,
    )


# ── 路由 ──

@app.route("/")
def dashboard():
    industries = load_all_industries()
    now = date.today()
    cross = load_yaml(CROSS_FILE)

    current_month_events = get_current_month_events(industries)
    upcoming = get_upcoming_events(industries, days=14)

    # 月度热点行业统计
    industry_event_count = {}
    for ev in current_month_events:
        ind = ev["industry"]
        industry_event_count[ind] = industry_event_count.get(ind, 0) + 1
    hot_industries = sorted(industry_event_count.items(), key=lambda x: -x[1])

    # 跨行业联动
    cross_events = cross.get("cross_events", [])
    month_str = f"{now.year}-{now.month:02d}"
    current_cross = [e for e in cross_events if e.get("date", "").startswith(month_str)]

    # 行业 ETF 映射
    etf_data = load_yaml(ETF_FILE)
    etf_mapping = etf_data.get("mapping", {}) if etf_data else {}

    # 行业新闻
    news_items = news.get_news()

    # 待审核事件数
    detected_events = news.load_detected_events()
    pending_count = len([e for e in detected_events if e.get("status") == "pending"])

    return render_template(
        "dashboard.html",
        now=now,
        industries=industries,
        current_month_events=current_month_events,
        upcoming=upcoming,
        hot_industries=hot_industries,
        cross_events=current_cross,
        news_items=news_items,
        pending_count=pending_count,
        etf_mapping=etf_mapping,
        get_importance_color=get_importance_color,
        get_importance_label=get_importance_label,
        get_action_color=get_action_color,
    )


@app.route("/calendar")
def calendar():
    industries = load_all_industries()
    now = date.today()
    cross = load_yaml(CROSS_FILE)

    # 按月聚合事件
    all_events = []
    for code, ind in industries.items():
        for ev in ind.get("events", []):
            all_events.append({
                **ev,
                "industry": ind["industry"],
                "industry_code": code,
            })

    # 构建月度数据结构
    months = []
    for m in range(1, 13):
        month_str = f"{now.year}-{m:02d}"
        month_events = [e for e in all_events if e.get("date", "").startswith(month_str)]
        month_events.sort(key=lambda e: e.get("date", ""))
        # 按重要性分组
        by_importance = {5: [], 4: [], 3: [], 2: [], 1: []}
        for ev in month_events:
            by_importance[ev.get("importance", 3)].append(ev)
        months.append({
            "num": m,
            "name": f"{m}月",
            "is_current": m == now.month,
            "events": month_events,
            "by_importance": by_importance,
            "total": len(month_events),
            "top_count": len(by_importance[5]) + len(by_importance[4]),
        })

    return render_template(
        "calendar.html",
        now=now,
        months=months,
        get_importance_color=get_importance_color,
        get_importance_label=get_importance_label,
        get_action_color=get_action_color,
    )


@app.route("/panorama")
def panorama():
    industries = load_all_industries()
    cross = load_yaml(CROSS_FILE)
    now = date.today()

    # 构建 12×11 矩阵
    months_names = ["1月", "2月", "3月", "4月", "5月", "6月",
                    "7月", "8月", "9月", "10月", "11月", "12月"]
    industry_list = []
    for code, ind in industries.items():
        row = {
            "code": code,
            "name": ind["industry"],
            "months": [],
        }
        for m in range(1, 13):
            month_str = f"{now.year}-{m:02d}"
            m_events = [e for e in ind.get("events", []) if e.get("date", "").startswith(month_str)]
            top = [e for e in m_events if e.get("importance", 0) >= 4]
            row["months"].append({
                "num": m,
                "events": m_events,
                "top_events": top,
                "count": len(m_events),
                "top_count": len(top),
            })
        industry_list.append(row)

    return render_template(
        "panorama.html",
        now=now,
        industry_list=industry_list,
        months_names=months_names,
        get_importance_color=get_importance_color,
        get_importance_label=get_importance_label,
    )


@app.route("/industry/<code>")
def industry_detail(code):
    industries = load_all_industries()
    if code not in industries:
        abort(404)
    ind = industries[code]
    cross = load_yaml(CROSS_FILE)

    # 获取关联行业
    affinity = cross.get("affinity_matrix", {})
    related = affinity.get(ind["industry"], {})
    related_info = []
    for rel_name, strength in sorted(related.items(), key=lambda x: -x[1]):
        for c, v in industries.items():
            if v["industry"] == rel_name:
                related_info.append({"code": c, "name": rel_name, "strength": strength})
                break

    # 加载组合池数据用于关联展示
    portfolio = load_yaml(PORTFOLIO_FILE)
    portfolio_map = {}
    for s in portfolio.get("stocks", []):
        portfolio_map[s.get("code", "")] = s

    return render_template(
        "industry.html",
        ind=ind,
        related=related_info,
        portfolio_map=portfolio_map,
        get_importance_color=get_importance_color,
        get_importance_label=get_importance_label,
        get_action_color=get_action_color,
    )


@app.route("/portfolio")
def portfolio():
    portfolio = load_yaml(PORTFOLIO_FILE)
    stocks = portfolio.get("stocks", [])
    industries = load_all_industries()

    # 按行业分组
    by_industry = {}
    for s in stocks:
        ind_name = s.get("industry", "其他")
        by_industry.setdefault(ind_name, []).append(s)

    # 行业名 → code 映射（用于跳转链接）
    industry_code_map = {}
    for code, ind in industries.items():
        industry_code_map[ind["industry"]] = code

    return render_template(
        "portfolio.html",
        stocks=stocks,
        by_industry=by_industry,
        industry_code_map=industry_code_map,
        get_action_color=get_action_color,
    )


@app.route("/linkage")
def linkage():
    cross = load_yaml(CROSS_FILE)
    raw_affinity = cross.get("affinity_matrix", {})
    cross_events = cross.get("cross_events", [])
    industries = load_all_industries()

    # 用全量11个行业构建完整矩阵，保证对称
    all_ind_names = [ind["industry"] for ind in industries.values()]
    affinity = {}
    for row_name in all_ind_names:
        row = {}
        for col_name in all_ind_names:
            val = raw_affinity.get(row_name, {}).get(col_name, 0)
            if val == 0:
                val = raw_affinity.get(col_name, {}).get(row_name, 0)
            row[col_name] = val
        affinity[row_name] = row

    return render_template(
        "linkage.html",
        affinity=affinity,
        cross_events=cross_events,
        industries=industries,
        ind_names=all_ind_names,
        get_importance_color=get_importance_color,
        get_importance_label=get_importance_label,
        get_action_color=get_action_color,
    )


@app.route("/api/news")
def api_news():
    """新闻刷新接口"""
    items = news.get_news(force_refresh=True)
    return jsonify({"count": len(items), "items": items[:30]})


# ── 设置页面 ──

@app.route("/settings")
def settings_page():
    sources = news.load_sources()
    detected_events = news.load_detected_events()

    # 获取已有行业名称列表（用于判断技能是否已创建行业日历）
    all_industries = load_all_industries()
    existing_industry_names = {ind["industry"] for ind in all_industries.values()}

    # 合并所有技能（内置可见 + 自定义）为统一列表
    builtin_visible = skills.get_visible_builtin_skills()
    all_skills_list = []
    for name, info in builtin_visible.items():
        all_skills_list.append({
            "name": name,
            "description": info.get("description", ""),
            "keywords": info.get("keywords", []),
            "builtin": True,
        })
    for s in skills.load_custom_skills()[0]:
        all_skills_list.append({
            "name": s["name"],
            "description": s.get("description", ""),
            "keywords": s.get("keywords", []),
            "builtin": False,
            "id": s.get("id", ""),
        })

    return render_template(
        "settings.html",
        active_page="settings",
        sources=sources,
        detected_events=detected_events,
        industry_keywords=skills.get_all_keywords(),
        custom_skills=skills.load_custom_skills()[0],
        builtin_skills=builtin_visible,
        all_skills_list=all_skills_list,
        hidden_builtins=skills.get_hidden_builtins(),
        existing_industry_names=existing_industry_names,
        llm_config=llm.load_config(),
    )


# ── 新闻源管理 API ──

@app.route("/api/sources/add", methods=["POST"])
def api_add_source():
    data = request.get_json()
    if not data or not data.get("name") or not data.get("url"):
        return jsonify({"ok": False, "error": "名称和URL不能为空"}), 400

    fields = {}
    if data.get("items_path"):
        fields["items_path"] = data["items_path"]
    if data.get("title_field"):
        fields["title"] = data["title_field"]
    if data.get("summary_field"):
        fields["summary"] = data["summary_field"]
    if data.get("time_field"):
        fields["time"] = data["time_field"]

    src_id = news.add_source(
        name=data["name"],
        url=data["url"],
        source_type=data.get("type", "json"),
        encoding=data.get("encoding", "utf-8"),
        fields=fields,
    )
    return jsonify({"ok": True, "id": src_id})


@app.route("/api/sources/toggle", methods=["POST"])
def api_toggle_source():
    data = request.get_json()
    news.toggle_source(data["id"])
    return jsonify({"ok": True})


@app.route("/api/sources/delete", methods=["POST"])
def api_delete_source():
    data = request.get_json()
    news.remove_source(data["id"])
    return jsonify({"ok": True})


@app.route("/api/sources/update", methods=["POST"])
def api_update_source():
    """更新新闻源字段"""
    data = request.get_json()
    if not data or not data.get("id"):
        return jsonify({"ok": False, "error": "缺少源ID"}), 400
    upd = {}
    for key in ["name", "url", "type", "encoding", "enabled"]:
        if key in data:
            upd[key] = data[key]
    if data.get("items_path"):
        upd["items_path"] = data["items_path"]
    fields = {}
    if data.get("title_field"):
        fields["title"] = data["title_field"]
    if data.get("summary_field"):
        fields["summary"] = data["summary_field"]
    if data.get("time_field"):
        fields["time"] = data["time_field"]
    if fields:
        upd["fields"] = fields
    news.update_source(data["id"], upd)
    return jsonify({"ok": True})


# ── 事件审核 API ──

@app.route("/api/events/accept", methods=["POST"])
def api_accept_event():
    data = request.get_json()
    # 如果携带了事件字段参数，走带详情写入
    if data and data.get("fields"):
        ok, msg = news.accept_event_with_details(data["idx"], data["fields"])
        return jsonify({"ok": ok, "error": None if ok else msg})
    news.accept_event(data["idx"])
    return jsonify({"ok": True})


@app.route("/api/events/reject", methods=["POST"])
def api_reject_event():
    data = request.get_json()
    news.reject_event(data["idx"])
    return jsonify({"ok": True})


# ── 行业事件编辑 API ──

def _find_industry_file(industry_name):
    """按行业名查找对应的数据文件路径"""
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith(".yaml"):
            fpath = os.path.join(DATA_DIR, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f) or {}
                    if data.get("industry") == industry_name:
                        return fpath, data
                except Exception:
                    continue
    return None, None


def _save_industry_data(fpath, data):
    """保存行业数据文件"""
    with open(fpath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


@app.route("/api/events/update", methods=["POST"])
def api_update_event():
    """更新一个行业事件"""
    data = request.get_json()
    industry = data.get("industry")
    idx = data.get("idx")
    fields = data.get("fields", {})

    if industry is None or idx is None:
        return jsonify({"ok": False, "error": "缺少 industry 或 idx"}), 400

    fpath, ind_data = _find_industry_file(industry)
    if not fpath:
        return jsonify({"ok": False, "error": f"未找到行业 '{industry}'"}), 404

    events = ind_data.get("events", [])
    if idx < 0 or idx >= len(events):
        return jsonify({"ok": False, "error": "事件索引无效"}), 400

    event = events[idx]
    for key, val in fields.items():
        if val is not None:
            event[key] = val

    ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_industry_data(fpath, ind_data)
    return jsonify({"ok": True})


@app.route("/api/events/add", methods=["POST"])
def api_add_event():
    """新增一个行业事件"""
    data = request.get_json()
    industry = data.get("industry")

    if not industry:
        return jsonify({"ok": False, "error": "缺少行业名称"}), 400

    fpath, ind_data = _find_industry_file(industry)
    if not fpath:
        return jsonify({"ok": False, "error": f"未找到行业 '{industry}'"}), 404

    events = ind_data.setdefault("events", [])
    new_event = {
        "date": data.get("date", "2026-06"),
        "date_precision": data.get("date_precision", "month"),
        "name": data.get("name", "新事件"),
        "importance": data.get("importance", 3),
        "type": data.get("type", "other"),
        "description": data.get("description", ""),
        "confirmed": data.get("confirmed", False),
    }
    if data.get("impact"):
        new_event["impact"] = data["impact"]
    events.append(new_event)

    ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_industry_data(fpath, ind_data)
    return jsonify({"ok": True, "idx": len(events) - 1})


@app.route("/api/events/delete", methods=["POST"])
def api_delete_event():
    """删除一个行业事件"""
    data = request.get_json()
    industry = data.get("industry")
    idx = data.get("idx")

    if industry is None or idx is None:
        return jsonify({"ok": False, "error": "缺少 industry 或 idx"}), 400

    fpath, ind_data = _find_industry_file(industry)
    if not fpath:
        return jsonify({"ok": False, "error": f"未找到行业 '{industry}'"}), 404

    events = ind_data.get("events", [])
    if idx < 0 or idx >= len(events):
        return jsonify({"ok": False, "error": "事件索引无效"}), 400

    del events[idx]
    ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_industry_data(fpath, ind_data)
    return jsonify({"ok": True})


# ── 技能管理 API ──

@app.route("/api/skills/add", methods=["POST"])
def api_add_skill():
    data = request.get_json()
    if not data or not data.get("name") or not data.get("keywords"):
        return jsonify({"ok": False, "error": "名称和关键词不能为空"}), 400

    keywords = data["keywords"]
    if isinstance(keywords, str):
        keywords = skills.normalize_keywords(keywords)
    if not keywords:
        return jsonify({"ok": False, "error": "至少需要一个关键词"}), 400

    name = data["name"]
    description = data.get("description", "")

    ok, msg = skills.add_skill(
        name=name,
        keywords=keywords,
        description=description,
    )
    if not ok:
        return jsonify({"ok": ok, "error": msg}), 400

    # 自动创建关联的行业数据文件
    auto_industry = data.get("auto_industry", True)  # 默认自动创建
    industry_result = None
    if auto_industry:
        ind_ok, ind_msg, ind_file = skills.create_industry_file(name, keywords, description)
        if ind_ok:
            industry_result = {"file": ind_file}
        else:
            industry_result = {"info": ind_msg}

    return jsonify({
        "ok": True,
        "industry": industry_result,
    })


@app.route("/api/skills/update", methods=["POST"])
def api_update_skill():
    """更新自定义技能（名称、关键词、描述）"""
    data = request.get_json()
    if not data or not data.get("id"):
        return jsonify({"ok": False, "error": "技能ID不能为空"}), 400

    skill_id = data["id"]
    name = data.get("name")
    keywords = data.get("keywords")
    description = data.get("description")

    if keywords and isinstance(keywords, str):
        keywords = skills.normalize_keywords(keywords)

    ok, msg = skills.update_skill(skill_id, name=name, keywords=keywords, description=description)
    return jsonify({"ok": ok, "error": None if ok else msg})


@app.route("/api/skills/delete", methods=["POST"])
def api_delete_skill():
    data = request.get_json()
    skills.delete_skill(data["id"])
    return jsonify({"ok": True})


@app.route("/api/skills/hide", methods=["POST"])
def api_hide_builtin():
    data = request.get_json()
    ok, msg = skills.hide_builtin_skill(data["name"])
    return jsonify({"ok": ok, "error": None if ok else msg})


@app.route("/api/skills/restore", methods=["POST"])
def api_restore_builtin():
    data = request.get_json()
    ok, msg = skills.restore_builtin_skill(data["name"])
    return jsonify({"ok": ok, "error": None if ok else msg})


@app.route("/api/skills/create-industry", methods=["POST"])
def api_create_skill_industry():
    """从技能创建行业数据文件"""
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"ok": False, "error": "技能名称不能为空"}), 400

    name = data["name"]
    # 从 custom skills 获取关键词和描述
    all_skills = skills.get_all_skills()
    skill_info = all_skills.get(name)
    if not skill_info:
        return jsonify({"ok": False, "error": f"未找到技能 '{name}'"}), 404

    keywords = skill_info.get("keywords", [])
    description = skill_info.get("description", "")

    ind_ok, ind_msg, ind_file = skills.create_industry_file(name, keywords, description)
    return jsonify({
        "ok": ind_ok,
        "error": None if ind_ok else ind_msg,
        "file": ind_file if ind_ok else None,
    })


@app.route("/api/skills/generate-calendar", methods=["POST"])
def api_generate_skill_calendar():
    """用 LLM 为技能对应的行业生成日历事件"""
    data = request.get_json()
    if not data or not data.get("industry"):
        return jsonify({"ok": False, "error": "行业名称不能为空"}), 400

    industry_name = data["industry"]
    provider = data.get("provider") or llm.load_config().get("default_provider", "deepseek")

    # 获取行业信息
    all_skills = skills.get_all_skills()
    skill_info = all_skills.get(industry_name, {})
    keywords = skill_info.get("keywords", [])
    description = skill_info.get("description", "")

    result = llm.generate_calendar_events(
        industry_name=industry_name,
        description=description,
        keywords=keywords,
        provider_key=provider,
    )

    if not result.get("ok"):
        return jsonify(result)

    # 将生成的事件写入行业数据文件
    ind_dir = os.path.join(BASE_DIR, "data", "industries")
    target_file = None
    for fname in sorted(os.listdir(ind_dir)):
        if fname.endswith(".yaml"):
            fpath = os.path.join(ind_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                try:
                    ind_data = yaml.safe_load(f) or {}
                    if ind_data.get("industry") == industry_name:
                        target_file = fpath
                        break
                except Exception:
                    continue

    if target_file:
        with open(target_file, "r", encoding="utf-8") as f:
            ind_data = yaml.safe_load(f) or {}

        cal_data = result["content"]
        if cal_data.get("events"):
            ind_data["events"] = cal_data["events"]
        if cal_data.get("monitors"):
            ind_data["monitors"] = cal_data.get("monitors", [])
        if cal_data.get("core_stocks"):
            existing = ind_data.get("core_stocks", [])
            existing_codes = {s.get("code") for s in existing}
            for s in cal_data["core_stocks"]:
                if s.get("code") not in existing_codes:
                    existing.append(s)
            ind_data["core_stocks"] = existing
        ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")

        with open(target_file, "w", encoding="utf-8") as f:
            yaml.dump(ind_data, f, allow_unicode=True, sort_keys=False)

        return jsonify({
            "ok": True,
            "event_count": len(cal_data.get("events", [])),
            "file": os.path.basename(target_file),
            "raw": result.get("raw", ""),
        })
    else:
        return jsonify({
            "ok": True,
            "event_count": len(result["content"].get("events", [])),
            "raw": result.get("raw", ""),
            "warning": "未找到行业文件，事件未保存",
        })


# ── 关注行业管理 API ──

@app.route("/api/follow/toggle", methods=["POST"])
def api_follow_toggle():
    """切换关注/取关"""
    data = request.get_json()
    name = data.get("name") if data else None
    if not name:
        return jsonify({"ok": False, "error": "行业名称不能为空"}), 400
    new_state = followed.toggle(name)
    return jsonify({"ok": True, "followed": new_state})


@app.route("/api/follow/quick-add", methods=["POST"])
def api_follow_quick_add():
    """快速新增行业并自动关注"""
    data = request.get_json()
    if not data or not data.get("name") or not data.get("keywords"):
        return jsonify({"ok": False, "error": "名称和关键词不能为空"}), 400

    name = data["name"]
    keywords = data["keywords"]
    if isinstance(keywords, str):
        keywords = skills.normalize_keywords(keywords)

    # 1. 创建 custom skill
    ok, msg = skills.add_skill(name, keywords, description=data.get("description", ""))
    if not ok and "已存在" not in msg:
        return jsonify({"ok": False, "error": msg})

    # 2. 创建 industry YAML 文件
    ind_ok, ind_msg, ind_file = skills.create_industry_file(name, keywords, description=data.get("description", ""))
    if not ind_ok and "已存在" not in ind_msg:
        return jsonify({"ok": False, "error": f"行业创建失败: {ind_msg}"})

    # 3. 关注该行业
    followed.follow(name)

    return jsonify({"ok": True, "name": name, "followed": True})


# ── 智能分析 ──

@app.route("/analysis")
def analysis_page():
    enabled_providers = llm.get_enabled_providers()
    presets = llm.get_available_presets()
    # 加载各预设的完整文本，转为 JSON 供前端使用
    prompt_texts = {}
    for key in presets:
        prompt_texts[key] = {
            "industry_report": llm.get_preset_prompt(key, "industry_report"),
            "calendar_generation": llm.get_preset_prompt(key, "calendar_generation"),
        }
    return render_template(
        "analysis.html",
        active_page="analysis",
        enabled_providers=enabled_providers,
        custom_skills=skills.load_custom_skills()[0],
        prompt_presets=presets,
        prompt_texts=prompt_texts,
    )


@app.route("/api/analysis/generate", methods=["POST"])
def api_generate_report():
    data = request.get_json()
    if not data or not data.get("industry"):
        return jsonify({"ok": False, "error": "请选择行业"}), 400

    industry = data["industry"]
    provider = data.get("provider") or llm.load_config().get("default_provider", "deepseek")
    extra = data.get("extra_instructions", "")
    save_to_calendar = data.get("save_to_calendar", False)
    custom_prompt = data.get("custom_prompt", "")

    # 检查是否有可用的 LLM 厂商
    enabled = llm.get_enabled_providers()
    provider_cfg = llm.load_config().get("providers", {}).get(provider, {})
    has_api_key = provider_cfg.get("api_key") or provider == "ollama"
    if not enabled or not has_api_key:
        return jsonify({
            "ok": True,
            "content": llm.MOCK_INDUSTRY_REPORT,
            "mock": True,
            "warning": "未配置有效的 API Key，展示示例报告。请在设置中配置大模型。",
        })

    if save_to_calendar:
        return _generate_and_save_events(industry, provider, extra, custom_prompt)

    result = llm.generate_industry_report(
        industry=industry,
        provider_key=provider,
        extra_instructions=extra,
        custom_prompt=custom_prompt,
    )
    return jsonify(result)


def _generate_and_save_events(industry, provider, extra, custom_prompt=""):
    """生成日历事件并写入行业 YAML 文件"""
    fpath, ind_data = _find_industry_file(industry)
    if not fpath:
        return jsonify({"ok": False, "error": f"未找到行业 [{industry}] 的数据文件"}), 404

    description = ind_data.get("description", "")
    if extra:
        description += f"（额外关注：{extra}）"
    tags = ind_data.get("tags", [])

    result = llm.generate_calendar_events(
        industry_name=industry,
        description=description,
        keywords=tags,
        provider_key=provider,
        extra_instructions=extra,
        custom_prompt=custom_prompt,
    )
    if not result.get("ok"):
        return jsonify(result)

    content = result.get("content", {})
    events = content.get("events", [])
    monitors = content.get("monitors", [])

    if not events:
        return jsonify({"ok": False, "error": "AI 未生成有效事件数据"})

    # 合并到现有数据（按名称+日期去重）
    existing_events = ind_data.get("events", [])
    existing_keys = {(e.get("name", ""), e.get("date", "")) for e in existing_events}

    new_count = 0
    for ev in events:
        key = (ev.get("name", ""), ev.get("date", ""))
        if key not in existing_keys:
            existing_events.append(ev)
            existing_keys.add(key)
            new_count += 1
    ind_data["events"] = existing_events

    # 合并 monitors（按 indicator 去重）
    if monitors:
        existing_monitors = ind_data.get("monitors", [])
        existing_inds = {m.get("indicator") for m in existing_monitors}
        for m in monitors:
            if m.get("indicator") not in existing_inds:
                existing_monitors.append(m)
                existing_inds.add(m.get("indicator"))
        ind_data["monitors"] = existing_monitors

    # 合并 core_stocks（按 code 去重）
    if content.get("core_stocks"):
        existing = ind_data.get("core_stocks", [])
        existing_codes = {s.get("code") for s in existing}
        for s in content["core_stocks"]:
            if s.get("code") not in existing_codes:
                existing.append(s)
        ind_data["core_stocks"] = existing

    ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_industry_data(fpath, ind_data)

    # 将事件格式化为可读报告
    report_lines = [
        f"# {industry} — 日历事件（AI 生成）",
        f"共新增 {new_count} 个事件（跳过 {len(events) - new_count} 个重复）\n",
    ]
    monthly = defaultdict(list)
    for ev in events:
        monthly[ev.get("date", "")[:7]].append(ev)

    for month in sorted(monthly.keys()):
        report_lines.append(f"## {month}")
        for ev in monthly[month]:
            stars = "★" * ev.get("importance", 3)
            tag = "✓" if ev.get("confirmed") else "~"
            line = f"- [{tag}] {stars} **{ev.get('name', '')}**"
            if ev.get("description"):
                line += f"\n  {ev['description']}"
            report_lines.append(line)
        report_lines.append("")

    return jsonify({
        "ok": True,
        "content": "\n".join(report_lines),
        "saved": True,
        "new_events": new_count,
    })


# ── LLM 配置 API ──

@app.route("/api/llm/config", methods=["POST"])
def api_save_llm_config():
    data = request.get_json()
    if not data or "providers" not in data:
        return jsonify({"ok": False, "error": "无效的配置数据"}), 400

    config = llm.load_config()
    for key, cfg in data["providers"].items():
        if key in config["providers"]:
            if "enabled" in cfg:
                config["providers"][key]["enabled"] = cfg["enabled"]
            if "api_key" in cfg:
                config["providers"][key]["api_key"] = cfg["api_key"]
            if "base_url" in cfg:
                config["providers"][key]["base_url"] = cfg["base_url"]
            if "model" in cfg:
                config["providers"][key]["model"] = cfg["model"]

    llm.save_config(config)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    # 启动时刷新新闻
    print("[新闻] 首次加载中...")
    news.refresh_news()
    print(f"行业投资日历系统已启动 → http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
