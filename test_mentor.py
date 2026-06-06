"""MENTOR 三阶段测试脚本 — 以 6G 通信为案例"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "web"))

import llm
import yaml

INDUSTRY = "6G通信"

def load_industry_data(name):
    ind_dir = os.path.join(os.path.dirname(__file__), "data", "industries")
    for fname in sorted(os.listdir(ind_dir)):
        if fname.endswith(".yaml"):
            with open(os.path.join(ind_dir, fname), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                if data.get("industry") == name:
                    return data
    return None

data = load_industry_data(INDUSTRY)
if not data:
    print(f"未找到行业 {INDUSTRY}")
    sys.exit(1)

events_summary = "\n".join(
    f"- {e.get('date','')} [{'✓' if e.get('confirmed') else '~'}] ★{e.get('importance',3)} {e.get('name','')}"
    for e in data.get("events", [])
)

stocks_summary = "\n".join(
    f"- {s.get('code','')} {s.get('name','')} ({s.get('sector','')})"
    for s in data.get("core_stocks", [])
)

print(f"{'='*60}")
print(f"MENTOR 三阶段测试 — {INDUSTRY}")
print(f"{'='*60}\n")

# ── Stage 1: 热点事件检测 ──
print("== Stage 1: 热点事件检测与排序 ==\n")

stage1_prompt = f"""你是一位叙事经济学分析师。请分析以下 {INDUSTRY} 行业的事件数据，找出当前最关键的叙事热点。

## 行业事件日历（2026年）
{events_summary}

## 核心标的
{stocks_summary}

## 任务
1. 从上述事件中识别出当前最热的 3-5 个关键叙事（narrative），按热度排序
2. 对每个叙事评估其传播力、影响范围、所处阶段
3. 指出背后的核心驱动信号类型

请输出 JSON 格式：
{{
  "narratives": [
    {{
      "name": "叙事名称",
      "heat": "高/中/低",
      "stage": "萌芽/升温/高潮/消退",
      "scope": "影响范围",
      "signal_type": "政策/技术/商业/地缘",
      "evidence": "支撑证据",
      "key_dates": ["关键时间节点"]
    }}
  ]
}}"""

print("[Stage 1] 调用 LLM...\n")
result1 = llm.call_llm(stage1_prompt, temperature=0.3, max_tokens=4096)
stage1_output = result1.get("content", "（Stage 1 无输出）") if result1.get("ok") else f"失败: {result1.get('error')}"
print(stage1_output)
print()

# ── Stage 2: 未来事件预测 ──
print("== Stage 2: 未来事件预测 ==\n")

stage2_prompt = f"""你是一位叙事经济学分析师。请基于以下 {INDUSTRY} 行业的数据和热点叙事，预测未来可能发生的重大事件。

## 行业事件日历
{events_summary}

## 核心标的
{stocks_summary}

## 当前热点叙事
{stage1_output}

## 任务
按"教师-学生迭代推理"方法，分析叙事演化方向，推断下一步催化事件。
输出 3-5 个预测事件，按发生概率从高到低排列：

{{
  "predictions": [
    {{
      "predicted_event": "预测事件名称",
      "probability": "高/中/低",
      "timeframe": "预期发生时间",
      "reasoning": "推演逻辑",
      "potential_impact": "对行业的影响描述",
      "impact_rating": 1-5,
      "affected_stocks": ["相关标的代码"]
    }}
  ]
}}"""

print("[Stage 2] 调用 LLM...\n")
result2 = llm.call_llm(stage2_prompt, temperature=0.3, max_tokens=4096)
stage2_output = result2.get("content", "（Stage 2 无输出）") if result2.get("ok") else f"失败: {result2.get('error')}"
print(stage2_output)
print()

# ── Stage 3: 行业影响排名 ──
print("== Stage 3: 行业影响排名 ==\n")

stage3_prompt = f"""你是一位叙事经济学分析师。请分析 {INDUSTRY} 行业的叙事如何传导并影响其他关联行业。

## {INDUSTRY} 的事件数据
{events_summary}

## 核心标的
{stocks_summary}

## 热点叙事
{stage1_output}

## 预测事件
{stage2_output}

## 任务
1. 分析 {INDUSTRY} 的叙事如何传导到其他行业
2. 列出最受影响的 5 个关联行业，按影响程度排序
3. 说明传导路径和影响方向

{{
  "industry_impact": [
    {{
      "industry": "受影响行业名称",
      "impact_direction": "正面/负面/中性",
      "impact_strength": 1-5,
      "transmission_path": "传导路径说明",
      "time_lag": "即时/1-2周/1-3月",
      "key_narrative": "触发传导的关键叙事"
    }}
  ],
  "cross_industry_signal": "跨行业联动的综合判断",
  "investment_implication": "投资含义总结"
}}"""

print("[Stage 3] 调用 LLM...\n")
result3 = llm.call_llm(stage3_prompt, temperature=0.3, max_tokens=4096)
stage3_output = result3.get("content", "（Stage 3 无输出）") if result3.get("ok") else f"失败: {result3.get('error')}"
print(stage3_output)

print(f"\n{'='*60}")
print("MENTOR 三阶段测试完成")
print(f"{'='*60}")
