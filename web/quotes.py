"""实时行情模块 — ETF 实时报价获取（腾讯行情接口）"""

import re
import time
from urllib.request import urlopen, Request

TENCENT_URL = "http://qt.gtimg.cn/q="
CACHE_TTL = 60  # 缓存有效期（秒）

# ── 交易所前缀映射 ──
EXCHANGE_PREFIX = {"SH": "sh", "SZ": "sz"}

# ── 缓存 ──
_cache = {"data": None, "timestamp": 0}


def build_secid(exchange, code):
    """将 SH/SZ + 代码转为腾讯格式（如 sh515050, sz159851）"""
    prefix = EXCHANGE_PREFIX.get(exchange.upper(), "sh")
    return f"{prefix}{code}"


def _parse_tencent_response(raw_text):
    """解析腾讯行情接口返回的文本

    返回 dict: {code: {name, price, change_pct, ...}}
    腾讯格式（按 ~ 分割）：
        1: name, 2: code, 3: price, 4: prev_close
        31: datetime(YYYYMMDDHHMMSS), 32: change, 33: change_pct
    """
    results = {}
    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("v_"):
            continue
        # 提取引号内的内容
        m = re.search(r'"(.+)"', line)
        if not m:
            continue
        fields = m.group(1).split("~")
        if len(fields) < 34:
            continue

        code = fields[2]
        price_str = fields[3].strip()
        change_pct_str = fields[33].strip()

        price = float(price_str) if price_str else None
        change_pct = float(change_pct_str) if change_pct_str else 0.0

        results[code] = {
            "code": code,
            "name": fields[1],
            "price": price,
            "change_pct": change_pct,
        }
    return results


def fetch_quotes_from_api(secids):
    """调用腾讯行情接口获取实时报价"""
    if not secids:
        return {}
    url = TENCENT_URL + ",".join(secids)
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk")
    except Exception:
        return {}
    return _parse_tencent_response(raw)


def get_quotes(etf_mapping, force_refresh=False):
    """获取所有行业 ETF 实时行情，按涨跌幅绝对值排序

    参数:
        etf_mapping: dict, 格式 {行业名: {code, name, exchange, ...}}
        force_refresh: bool, 是否强制刷新缓存

    返回:
        dict: {quotes: {行业名: {...}}, sorted_industries: [...], updated_at, total}
    """
    now = time.time()

    # 缓存命中
    if not force_refresh and _cache["data"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["data"]

    # 构建去重 secid 列表
    code_to_industries = {}  # ETF代码 → [{行业名, exchange, etf_name}]
    for ind_name, etf in etf_mapping.items():
        code = etf.get("code", "")
        exch = etf.get("exchange", "SH")
        if not code:
            continue
        if code not in code_to_industries:
            code_to_industries[code] = []
        code_to_industries[code].append({
            "name": ind_name,
            "code": code,
            "exchange": exch,
            "etf_name": etf.get("name", ""),
        })

    # 构建 secid 列表（去重后）
    unique_secids = []
    for code, _ in code_to_industries.items():
        exch = code_to_industries[code][0]["exchange"]
        unique_secids.append(build_secid(exch, code))

    api_results = fetch_quotes_from_api(unique_secids)

    # 展开回各行业
    quotes = {}
    for code, industries in code_to_industries.items():
        q = api_results.get(code, {})
        for ind_info in industries:
            entry = {
                "code": ind_info["code"],
                "name": ind_info["etf_name"],
                "exchange": ind_info["exchange"],
                "price": None,
                "change_pct": None,
                "api_ok": False,
            }
            if q and q.get("price") is not None:
                entry["price"] = q["price"]
                entry["change_pct"] = q.get("change_pct", 0.0)
                entry["api_ok"] = True
            quotes[ind_info["name"]] = entry

    # 按 |涨跌幅| 排序
    sorted_industries = sorted(
        quotes.keys(),
        key=lambda x: abs(quotes[x].get("change_pct") or 0),
        reverse=True,
    )

    ts = time.strftime("%H:%M:%S", time.localtime(now))

    result = {
        "quotes": quotes,
        "sorted_industries": sorted_industries,
        "updated_at": ts,
        "timestamp": int(now),
        "total": len(quotes),
    }

    _cache["data"] = result
    _cache["timestamp"] = now

    return result


def invalidate_cache():
    """清除缓存"""
    _cache["timestamp"] = 0
