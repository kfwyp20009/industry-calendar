# 行业投资日历系统

A 股主题投资日历，跟踪前沿行业催化事件，提供可视化仪表盘、事件日历、回测验证等功能。

![](https://img.shields.io/badge/Python-3.8%2B-blue) ![](https://img.shields.io/badge/license-MIT-green)

---

## 快速启动

```bash
pip install flask pyyaml
python launch.py
```

浏览器访问 `http://localhost:5000`

Windows 用户也可直接双击 `start.bat`，Mac/Linux 双击 `start.sh`。

---

## 功能

| 页面 | 说明 |
|------|------|
| 仪表盘 | 本月催化热度、行业 ETF 行情、回测概览 |
| 事件日历 | 月度事件视图，按行业筛选 |
| 全年全景 | 跨行业全年事件时间线 |
| 行业详情 | 单行业事件列表 + 核心标的池 |
| 核心标的 | 全行业标的池汇总 |
| 联动分析 | 跨行业事件联动图谱 |

---

## 内置行业示例

系统内置了 13 个行业作为参考（以下为前 3 个示例）：

| # | 行业 | 驱动类型 |
|---|------|---------|
| 1 | 6G通信 | 技术+标准 |
| 2 | 低空经济 | 政策+基建 |
| 3 | 卫星互联网 | 基建+国防 |

**完整列表见 `data/industries/` 目录。**

---

## 添加自定义行业

在 `data/industries/` 下创建 `YAML` 文件即可，格式如下：

```yaml
industry: "你的行业名称"
description: "一句话描述"
tags: [标签1, 标签2]
updated: "2026-06-01"

core_stocks:
  - code: "000001"
    name: "股票名称"
    reason: "入选理由"
    sector: "细分板块"

events:
  - date: "2026-07-15"
    title: "事件标题"
    importance: 3        # 1-4，4为最重要
    type: "政策/技术/产品/会议"
    description: "事件详情"
    category: "预期/跟踪/确认"
```

文件名建议按 `01-行业名称.yaml` 格式命名，系统按文件名排序加载。添加后重启服务即可生效。

---

## 项目结构

```
data/
  industries/      ← 行业事件数据（YAML），在此添加新行业
  stocks/           # 核心标的池
  etf_mapping.yaml  # 行业 ETF 映射
  cross-industry.yaml  # 跨行业联动
web/
  app.py           # Flask 后端
  templates/       # HTML 模板
launch.py          # 一键启动脚本
```

---

## License

MIT
