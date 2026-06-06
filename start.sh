#!/usr/bin/env bash
# 行业投资日历系统 — 一键启动（Mac / Linux）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo "  行业投资日历系统 — 启动中..."
echo "=============================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] 未找到 Python3"
    exit 1
fi
echo "[OK] Python 已就绪"

# Install deps
echo "[..] 检查依赖..."
pip3 install flask pyyaml -q 2>/dev/null || true
echo "[OK] 依赖就绪"

# Start
echo ""
echo "=============================================="
echo "  服务启动中..."
echo "  打开浏览器访问: http://localhost:5000"
echo "  按 Ctrl+C 停止服务"
echo "=============================================="
echo ""

cd "$SCRIPT_DIR"
python3 web/app.py
