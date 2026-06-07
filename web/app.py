"""行业投资日历系统 — 本地 Web 应用"""

import os
import sys
import calendar as _cal
from collections import defaultdict
from datetime import datetime, date, timedelta

import yaml
from icalendar import Calendar, Event as ICalEvent, Alarm
from flask import Flask, render_template, abort, jsonify, request, Response
import news
import skills
import llm
import followed
import quotes

# 数据同步模块（行业 YAML → portfolio / config 等派生数据）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
import sync_data

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
        # 为所有行业事件添加回测上下文
        enrich_events_with_backtest(
            [ev for ind in industries.values() for ev in ind.get("events", [])]
        )
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


def is_past_event(ev_date_str):
    """检查事件日期是否已过"""
    if not ev_date_str:
        return False
    try:
        ev_date = datetime.strptime(ev_date_str[:10], "%Y-%m-%d").date()
        return ev_date < date.today()
    except (ValueError, IndexError):
        return False


def get_backtest_badge(backtest):
    """获取回测状态标签"""
    if not backtest:
        return None
    status = backtest.get("status", "")
    badges = {
        "hit": {"label": "✓ 验证成功", "class": "bg-success"},
        "partial": {"label": "◐ 部分验证", "class": "bg-warning text-dark"},
        "miss": {"label": "✗ 未验证", "class": "bg-danger"},
        "unknown": {"label": "? 待验证", "class": "bg-secondary"},
    }
    return badges.get(status, None)


def enrich_events_with_backtest(events):
    """为事件列表添加回测上下文"""
    now = date.today()
    for ev in events:
        ev_date_str = ev.get("date", "")
        try:
            ev_date = datetime.strptime(ev_date_str[:10], "%Y-%m-%d").date() if ev_date_str else None
            ev["is_past"] = ev_date is not None and ev_date < now if ev_date else False
        except (ValueError, IndexError):
            ev["is_past"] = False
        if ev.get("backtest"):
            badge = get_backtest_badge(ev["backtest"])
            if badge:
                ev["backtest_badge"] = badge
    return events


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
        default_provider=llm.get_default_provider(),
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

    # 回测统计
    backtest_stats = {"hit": 0, "partial": 0, "miss": 0, "unknown": 0, "past_total": 0}
    for ev in current_month_events:
        if ev.get("is_past"):
            backtest_stats["past_total"] += 1
            bt = ev.get("backtest", {})
            s = bt.get("status", "unknown")
            backtest_stats[s] = backtest_stats.get(s, 0) + 1

    # 跨月份回测统计（仅取最近3个月以提升性能）
    past_months_backtest = []
    current_year = now.year
    for offset in range(1, 4):
        pm = now.month - offset
        py = current_year
        while pm < 1:
            pm += 12
            py -= 1
        if py < current_year:
            break
        month_str = f"{py}-{pm:02d}"
        month_events = []
        for code, ind in industries.items():
            for ev in ind.get("events", []):
                if ev.get("date", "").startswith(month_str) and ev.get("is_past"):
                    month_events.append({
                        **ev,
                        "industry": ind["industry"],
                        "industry_code": code,
                    })
        if month_events:
            month_stats = {"hit": 0, "partial": 0, "miss": 0, "unknown": 0, "total": len(month_events)}
            for ev in month_events:
                bt = ev.get("backtest", {})
                s = bt.get("status", "unknown")
                month_stats[s] = month_stats.get(s, 0) + 1
            past_months_backtest.append({
                "month": pm,
                "label": f"{pm}月",
                "stats": month_stats,
            })

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
        backtest_stats=backtest_stats,
        past_months_backtest=past_months_backtest,
    )


@app.route("/calendar")
def calendar():
    industries = load_all_industries()
    now = date.today()
    cross = load_yaml(CROSS_FILE)

    # 要显示的月份（默认当前月）
    try:
        display_month = int(request.args.get("month", now.month))
    except ValueError:
        display_month = now.month
    display_month = max(1, min(12, display_month))
    display_year = now.year

    # 收集所有事件
    all_events = []
    for code, ind in industries.items():
        for ev in ind.get("events", []):
            all_events.append({
                **ev,
                "industry": ind["industry"],
                "industry_code": code,
            })

    # 按月聚合（月份导航用）
    months = []
    for m in range(1, 13):
        month_str = f"{now.year}-{m:02d}"
        month_events = [e for e in all_events if e.get("date", "").startswith(month_str)]
        month_events.sort(key=lambda e: e.get("date", ""))
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

    # 当月事件按天索引
    month_str = f"{display_year}-{display_month:02d}"
    display_events = [e for e in all_events if e.get("date", "").startswith(month_str)]

    events_by_day = defaultdict(list)
    month_precision_events = []
    for ev in display_events:
        date_str = ev.get("date", "")
        if ev.get("date_precision") == "day" and len(date_str) >= 10:
            try:
                day_num = int(date_str[8:10])
                events_by_day[day_num].append(ev)
            except (ValueError, IndexError):
                month_precision_events.append(ev)
        else:
            month_precision_events.append(ev)

    # 当日事件的 JSON（给前端弹窗用）
    day_events_json = {}
    for day_num, ev_list in events_by_day.items():
        date_key = f"{month_str}-{day_num:02d}"
        day_events_json[date_key] = [{
            "name": e["name"],
            "industry": e["industry"],
            "importance": e.get("importance", 3),
            "type": e.get("type", ""),
            "description": e.get("description", ""),
            "confirmed": e.get("confirmed", False),
            "action": e.get("suggested_action", {}).get("action", "") if e.get("suggested_action") else "",
        } for e in ev_list]

    # 构建日历网格（周一为第一天）
    first_weekday, days_in_month = _cal.monthrange(display_year, display_month)
    # first_weekday: 0=Mon, 1=Tue, ..., 6=Sun

    today = date.today()
    calendar_grid = []
    week = []
    for _ in range(first_weekday):
        week.append(None)  # 填充空白
    for day in range(1, days_in_month + 1):
        is_today = (display_year == today.year and display_month == today.month and day == today.day)
        week.append({
            "day": day,
            "is_today": is_today,
            "events": events_by_day.get(day, []),
        })
        if len(week) == 7:
            calendar_grid.append(week)
            week = []
    if week:
        while len(week) < 7:
            week.append(None)
        calendar_grid.append(week)

    return render_template(
        "calendar.html",
        now=now,
        months=months,
        calendar_grid=calendar_grid,
        day_events_json=day_events_json,
        display_month=display_month,
        display_year=display_year,
        month_precision_events=month_precision_events,
        industries=industries,
        get_importance_color=get_importance_color,
        get_importance_label=get_importance_label,
        get_action_color=get_action_color,
    )


@app.route("/backtest")
def backtest_page():
    """回测总览页面"""
    industries = load_all_industries()
    now = date.today()

    # 聚合所有已过去且有回测数据的事件
    all_backtested = []
    for code, ind in industries.items():
        for ev in ind.get("events", []):
            if ev.get("backtest") and ev.get("is_past"):
                all_backtested.append({
                    **ev,
                    "industry": ind["industry"],
                    "industry_code": code,
                })
    all_backtested.sort(key=lambda e: e.get("date", ""), reverse=True)

    # 统计
    stats = {"hit": 0, "partial": 0, "miss": 0, "unknown": 0, "past_total": 0, "verified": 0}
    for ev in all_backtested:
        s = ev.get("backtest", {}).get("status", "unknown")
        stats[s] = stats.get(s, 0) + 1
    stats["past_total"] = len(all_backtested)
    stats["verified"] = stats["hit"] + stats["partial"] + stats["miss"]

    return render_template(
        "backtest.html",
        now=now,
        events=all_backtested,
        stats=stats,
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

    # 按行业分组（支持一股多行业）
    by_industry = {}
    for s in stocks:
        for ind_name in s.get("industries", ["其他"]):
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


@app.route("/api/etf-quotes")
def api_etf_quotes():
    """实时 ETF 行情接口"""
    etf_data = load_yaml(ETF_FILE)
    etf_mapping = etf_data.get("mapping", {}) if etf_data else {}
    force = request.args.get("force", "0") == "1"
    result = quotes.get_quotes(etf_mapping, force_refresh=force)
    return jsonify({"ok": True, **result})


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
    sync_data.sync_all()
    return jsonify({"ok": True})


@app.route("/api/events/reject", methods=["POST"])
def api_reject_event():
    data = request.get_json()
    news.reject_event(data["idx"])
    sync_data.sync_all()
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

    # 如果前端传入了独立的 backtest 字段，单独处理
    if "backtest" in data:
        if data["backtest"] is not None:
            event["backtest"] = data["backtest"]
            event["backtest"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        else:
            event.pop("backtest", None)

    ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_industry_data(fpath, ind_data)
    sync_data.sync_all()
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
    sync_data.sync_all()
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
    sync_data.sync_all()
    return jsonify({"ok": True})


# ── 回测数据 API ──

@app.route("/api/backtest/update", methods=["POST"])
def api_update_backtest():
    """更新一个事件的回测数据"""
    data = request.get_json()
    industry = data.get("industry")
    idx = data.get("idx")
    backtest = data.get("backtest", {})

    if industry is None or idx is None:
        return jsonify({"ok": False, "error": "缺少 industry 或 idx"}), 400
    if not backtest or "status" not in backtest:
        return jsonify({"ok": False, "error": "回测数据缺少 status"}), 400

    fpath, ind_data = _find_industry_file(industry)
    if not fpath:
        return jsonify({"ok": False, "error": f"未找到行业 '{industry}'"}), 404

    events = ind_data.get("events", [])
    if idx < 0 or idx >= len(events):
        return jsonify({"ok": False, "error": "事件索引无效"}), 400

    events[idx]["backtest"] = backtest
    events[idx]["backtest"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    ind_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_industry_data(fpath, ind_data)
    sync_data.sync_all()
    return jsonify({"ok": True})


@app.route("/api/backtest/stats")
def api_backtest_stats():
    """回测统计汇总"""
    industries = load_all_industries()
    stats = {"hit": 0, "partial": 0, "miss": 0, "unknown": 0, "total": 0, "past_total": 0}
    for ind in industries.values():
        for ev in ind.get("events", []):
            if ev.get("is_past"):
                stats["past_total"] += 1
                bt = ev.get("backtest", {})
                s = bt.get("status", "unknown")
                stats[s] = stats.get(s, 0) + 1
    stats["total"] = stats["hit"] + stats["partial"] + stats["miss"] + stats["unknown"]
    return jsonify({"ok": True, "stats": stats})


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
            # 同步 ETF 映射 + 跨行业联动
            etf_code = data.get("etf_code", "")
            etf_name = data.get("etf_name", "")
            skills.sync_etf_mapping(name, etf_code, etf_name)
            skills.sync_cross_industry(name)
        else:
            industry_result = {"info": ind_msg}

    return jsonify({
        "ok": True,
        "industry": industry_result,
        "sync": sync_data.sync_all(),
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


@app.route("/api/skills/update-keywords", methods=["POST"])
def api_update_skill_keywords():
    """按行业名称更新关键词（内置/自定义通用）"""
    data = request.get_json()
    name = data.get("name") if data else None
    keywords = data.get("keywords") if data else None
    if not name or keywords is None:
        return jsonify({"ok": False, "error": "缺少行业名称或关键词"}), 400
    ok, msg = skills.update_keywords_by_name(name, keywords)
    return jsonify({"ok": ok, "error": None if ok else msg})


@app.route("/api/skills/delete", methods=["POST"])
def api_delete_skill():
    """删除技能 → 同步清理所有关联数据"""
    data = request.get_json()

    # 先查出技能名称，用于后续清理
    skill_id = data["id"]
    skill_name = None
    for s in skills.load_custom_skills()[0]:
        if s.get("id") == skill_id:
            skill_name = s["name"]
            break

    # 删除技能 + 行业文件 + config
    skills.delete_skill(data["id"])

    # 清理关联数据
    if skill_name:
        skills.remove_from_etf_mapping(skill_name)
        skills.remove_from_cross_industry(skill_name)
        skills.remove_from_portfolio(skill_name)
        skills.remove_from_followed(skill_name)

    sync_data.sync_all()

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
    if ind_ok:
        # 同步 ETF 映射 + 跨行业联动
        skills.sync_etf_mapping(name)
        skills.sync_cross_industry(name)
    if ind_ok:
        sync_data.sync_all()
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

        sync_data.sync_all()

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
    """快速新增行业 → 自动同步所有关联数据"""
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

    # 2. 创建 industry YAML 文件（空骨架）
    ind_ok, ind_msg, ind_file = skills.create_industry_file(name, keywords, description=data.get("description", ""))
    if not ind_ok and "已存在" not in ind_msg:
        return jsonify({"ok": False, "error": f"行业创建失败: {ind_msg}"})

    # 3. 同步 ETF 映射（有代码则写入，无则留占位）
    etf_code = data.get("etf_code", "")
    etf_name = data.get("etf_name", "")
    skills.sync_etf_mapping(name, etf_code, etf_name)

    # 4. 同步跨行业联动（空矩阵行）
    skills.sync_cross_industry(name)

    # 5. 关注该行业
    followed.follow(name)

    # 6. 是否自动生成日历事件（前端在收到响应后异步触发）
    auto_calendar = data.get("auto_calendar", True)

    return jsonify({
        "ok": True,
        "name": name,
        "followed": True,
        "auto_calendar": auto_calendar,
        "industry_file": ind_file,
    })


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
    # 构建厂商→模型列表映射（给前端两级联动用）
    config = llm.load_config()
    provider_models = {}
    provider_names = {}
    for key, info in enabled_providers:
        if key in llm.BUILTIN_PROVIDERS:
            bi = llm.BUILTIN_PROVIDERS[key]
            provider_models[key] = bi["models"]
            provider_names[key] = bi["name"]
        else:
            provider_models[key] = info.get("models", [])
            provider_names[key] = info.get("name", key)
    # 每个厂商当前配置的默认模型
    provider_default_models = {}
    for key, _ in enabled_providers:
        cfg = config.get("providers", {}).get(key, {}) or config.get("custom_providers", {}).get(key, {})
        provider_default_models[key] = cfg.get("model", "")

    return render_template(
        "analysis.html",
        active_page="analysis",
        enabled_providers=enabled_providers,
        custom_skills=skills.load_custom_skills()[0],
        prompt_presets=presets,
        prompt_texts=prompt_texts,
        builtin_provider_keys=list(llm.BUILTIN_PROVIDERS.keys()),
        provider_models=provider_models,
        provider_names=provider_names,
        provider_default_models=provider_default_models,
    )


@app.route("/api/analysis/generate", methods=["POST"])
def api_generate_report():
    data = request.get_json()
    if not data or not data.get("industry"):
        return jsonify({"ok": False, "error": "请选择行业"}), 400

    industry = data["industry"]
    provider = data.get("provider") or llm.load_config().get("default_provider", "deepseek")
    model = data.get("model") or None
    extra = data.get("extra_instructions", "")
    save_to_calendar = data.get("save_to_calendar", False)
    custom_prompt = data.get("custom_prompt", "")

    # 检查是否有可用的 LLM 厂商
    enabled = llm.get_enabled_providers()
    config = llm.load_config()
    provider_cfg = config.get("providers", {}).get(provider, {}) or config.get("custom_providers", {}).get(provider, {})
    has_api_key = provider_cfg.get("api_key") or provider == "ollama"
    if not enabled or not has_api_key:
        return jsonify({
            "ok": True,
            "content": llm.MOCK_INDUSTRY_REPORT,
            "mock": True,
            "warning": "未配置有效的 API Key，展示示例报告。请在设置中配置大模型。",
        })

    if save_to_calendar:
        return _generate_and_save_events(industry, provider, extra, custom_prompt, model=model)

    result = llm.generate_industry_report(
        industry=industry,
        provider_key=provider,
        model=model,
        extra_instructions=extra,
        custom_prompt=custom_prompt,
    )
    return jsonify(result)


def _generate_and_save_events(industry, provider, extra, custom_prompt="", model=None):
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
        model=model,
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
    sync_data.sync_all()

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

    # 保存自定义厂商
    if "custom_providers" in data:
        custom = config.setdefault("custom_providers", {})
        for key, cfg in data["custom_providers"].items():
            if key in custom:
                if "enabled" in cfg:
                    custom[key]["enabled"] = cfg["enabled"]
                if "api_key" in cfg:
                    custom[key]["api_key"] = cfg["api_key"]
                if "base_url" in cfg:
                    custom[key]["base_url"] = cfg["base_url"]
                if "model" in cfg:
                    custom[key]["model"] = cfg["model"]

    llm.save_config(config)
    return jsonify({"ok": True})


@app.route("/api/llm/custom-provider/detect-models", methods=["POST"])
def api_detect_custom_provider_models():
    """探测自定义厂商的可用模型列表"""
    data = request.get_json()
    base_url = data.get("base_url") if data else None
    api_key = data.get("api_key") if data else ""
    if not base_url:
        return jsonify({"ok": False, "error": "接口地址不能为空"}), 400
    models, error = llm.detect_models(base_url, api_key)
    if models:
        return jsonify({"ok": True, "models": models})
    return jsonify({"ok": False, "error": error or "未能获取模型列表"}), 400


@app.route("/api/llm/custom-provider/add", methods=["POST"])
def api_add_custom_provider():
    data = request.get_json()
    key = data.get("key") if data else None
    name = data.get("name") if data else None
    base_url = data.get("base_url") if data else None
    models = data.get("models", "") if data else ""
    api_key = data.get("api_key", "") if data else ""
    model = data.get("model", "") if data else ""
    if not key or not name or not base_url:
        return jsonify({"ok": False, "error": "厂商标识、名称和接口地址不能为空"}), 400
    ok, msg = llm.add_custom_provider(key, name, base_url, models, api_key=api_key, model=model)
    return jsonify({"ok": ok, "error": None if ok else msg})


@app.route("/api/llm/custom-provider/delete", methods=["POST"])
def api_delete_custom_provider():
    data = request.get_json()
    key = data.get("key") if data else None
    if not key:
        return jsonify({"ok": False, "error": "厂商标识不能为空"}), 400
    ok, msg = llm.remove_custom_provider(key)
    return jsonify({"ok": ok, "error": None if ok else msg})


@app.route("/api/llm/default-provider/set", methods=["POST"])
def api_set_default_provider():
    """设置默认厂商"""
    data = request.get_json()
    provider_key = data.get("provider") if data else None
    if not provider_key:
        return jsonify({"ok": False, "error": "厂商不能为空"}), 400
    ok, msg = llm.set_default_provider(provider_key)
    return jsonify({"ok": ok, "error": msg if not ok else None})


# ── ICS 日历导出 ──


@app.route("/export/calendar.ics")
def export_calendar_ics():
    """导出行业事件为 ICS 日历文件（iPhone 订阅 / 导入）"""
    industries = load_all_industries()
    industry_filter = request.args.get("industry", "").strip()

    cal = Calendar()
    cal.add("prodid", "-//行业投资日历//hermes-industry-calendar//CN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "行业投资日历")
    cal.add("x-wr-timezone", "Asia/Shanghai")

    importance_labels = {5: "★★★★★", 4: "★★★★", 3: "★★★", 2: "★★", 1: "★"}
    type_colors = {"政策": "#e74c3c", "技术": "#3498db", "产品": "#2ecc71", "会议": "#f39c12"}

    now = datetime.now()

    for code, ind in industries.items():
        if industry_filter and code != industry_filter:
            continue
        industry_name = ind.get("industry", code)
        for ev in ind.get("events", []):
            ev_date_str = ev.get("date", "").strip()
            if not ev_date_str:
                continue
            try:
                dt = datetime.strptime(ev_date_str[:10], "%Y-%m-%d")
            except (ValueError, IndexError):
                continue

            title = ev.get("title", "")
            importance = ev.get("importance", 1)
            ev_type = ev.get("type", "")
            category = ev.get("category", "")
            ev_desc = ev.get("description", "")

            # 构建日程标题
            stars = importance_labels.get(importance, "")
            summary = f"[{industry_name}] {title} {stars}".strip()

            # 构建描述
            desc_parts = [
                f"行业：{industry_name}",
                f"类型：{ev_type}",
                f"重要性：{'★' * importance}{'☆' * (5 - importance)}",
            ]
            if category:
                desc_parts.append(f"阶段：{category}")
            if ev_desc:
                desc_parts.append("")
                desc_parts.append(ev_desc)

            # 从 core_stocks 提取相关标的
            stocks = ind.get("core_stocks", [])
            if stocks:
                desc_parts.append("")
                desc_parts.append("相关标的：")
                for s in stocks[:6]:
                    name = s.get("name", "")
                    reason = s.get("reason", "")
                    desc_parts.append(f"  {name}（{s.get('code', '')}）- {reason}" if reason else f"  {name}（{s.get('code', '')}）")

            description = "\n".join(desc_parts)

            uid = f"{code}-{ev_date_str[:10]}-{hash(title) & 0xffffffff:08x}@industry-calendar"

            ical_event = ICalEvent()
            ical_event.add("uid", uid)
            ical_event.add("dtstart", dt.date())
            ical_event.add("dtend", dt.date())
            ical_event.add("dtstamp", now)
            ical_event.add("summary", summary)
            ical_event.add("description", description)

            # 颜色按事件类型
            color = type_colors.get(ev_type, "#95a5a6")
            ical_event.add("color", color)
            ical_event.add("categories", [industry_name, ev_type, category] if category else [industry_name, ev_type])

            # 3 星以上加提醒
            if importance >= 3:
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("description", f"提醒：{summary}")
                alarm.add("trigger", timedelta(days=1) if importance >= 4 else timedelta(hours=3))
                ical_event.add_component(alarm)

            cal.add_component(ical_event)

    ics_content = cal.to_ical()

    return Response(
        ics_content,
        mimetype="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=industry-calendar.ics",
            "Cache-Control": "no-cache",
        },
    )


@app.route("/export/subscribe.ics")
def subscribe_calendar_ics():
    """用途同上，专为 iPhone 订阅日历优化（不强制下载）"""
    industries = load_all_industries()
    industry_filter = request.args.get("industry", "").strip()

    cal = Calendar()
    cal.add("prodid", "-//行业投资日历//hermes-industry-calendar//CN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "行业投资日历")
    cal.add("x-wr-timezone", "Asia/Shanghai")
    cal.add("refresh-interval", timedelta(days=1))  # 订阅日历每天自动刷新
    cal.add("x-published-ttl", timedelta(days=1))

    importance_labels = {5: "★★★★★", 4: "★★★★", 3: "★★★", 2: "★★", 1: "★"}
    type_colors = {"政策": "#e74c3c", "技术": "#3498db", "产品": "#2ecc71", "会议": "#f39c12"}
    now = datetime.now()

    for code, ind in industries.items():
        if industry_filter and code != industry_filter:
            continue
        industry_name = ind.get("industry", code)
        for ev in ind.get("events", []):
            ev_date_str = ev.get("date", "").strip()
            if not ev_date_str:
                continue
            try:
                dt = datetime.strptime(ev_date_str[:10], "%Y-%m-%d")
            except (ValueError, IndexError):
                continue

            title = ev.get("title", "")
            importance = ev.get("importance", 1)
            ev_type = ev.get("type", "")
            category = ev.get("category", "")
            ev_desc = ev.get("description", "")
            stars = importance_labels.get(importance, "")
            summary = f"[{industry_name}] {title} {stars}".strip()

            desc_parts = [
                f"行业：{industry_name}",
                f"类型：{ev_type}",
                f"重要性：{'★' * importance}{'☆' * (5 - importance)}",
            ]
            if category:
                desc_parts.append(f"阶段：{category}")
            if ev_desc:
                desc_parts.append("")
                desc_parts.append(ev_desc)

            description = "\n".join(desc_parts)
            uid = f"{code}-{ev_date_str[:10]}-{hash(title) & 0xffffffff:08x}@industry-calendar"

            ical_event = ICalEvent()
            ical_event.add("uid", uid)
            ical_event.add("dtstart", dt.date())
            ical_event.add("dtend", dt.date())
            ical_event.add("dtstamp", now)
            ical_event.add("summary", summary)
            ical_event.add("description", description)
            color = type_colors.get(ev_type, "#95a5a6")
            ical_event.add("color", color)
            ical_event.add("categories", [industry_name, ev_type, category] if category else [industry_name, ev_type])

            if importance >= 3:
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("description", f"提醒：{summary}")
                alarm.add("trigger", timedelta(days=1) if importance >= 4 else timedelta(hours=3))
                ical_event.add_component(alarm)

            cal.add_component(ical_event)

    ics_content = cal.to_ical()

    return Response(
        ics_content,
        mimetype="text/calendar; charset=utf-8",
        headers={
            "Content-Type": "text/calendar; charset=utf-8",
            "Cache-Control": "no-cache",
        },
    )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    # 启动时同步数据（行业 YAML → portfolio / config / etf / cross-industry）
    print("[同步] 数据同步中...")
    sync_result = sync_data.sync_all()
    print(f"[同步] {sync_result['message']}")
    # 启动时刷新新闻
    print("[新闻] 首次加载中...")
    news.refresh_news()
    print(f"行业投资日历系统已启动 → http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
