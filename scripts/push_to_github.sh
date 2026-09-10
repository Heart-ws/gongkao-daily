#!/usr/bin/env bash
# 把「公考日报」推送到 GitHub，并触发一次工作流把站点发布上线。
#
# 前置条件（只需做一次）：
#   1. 已在 GitHub 上创建空仓库 Heart-ws/gongkao-daily（Public，不要勾选 README）
#   2. 本机 SSH 公钥已添加到 GitHub（本机早已配置好，可用 ssh -T git@github.com 验证）
#
# 用法：
#   bash scripts/push_to_github.sh           # 推送到默认仓库 Heart-ws/gongkao-daily
#   bash scripts/push_to_github.sh 仓库名      # 换一个仓库名
set -euo pipefail

REPO_NAME="${1:-gongkao-daily}"
OWNER="Heart-ws"
REMOTE="git@github.com:${OWNER}/${REPO_NAME}.git"

cd "$(dirname "$0")/.."
echo "项目目录：$(pwd)"

# ---------- 1. 检查前置条件 ----------
echo ""
echo "[1/4] 检查 SSH 连通性…"
if ! ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  echo "❌ SSH 认证失败。请先确认 SSH 公钥已添加到 GitHub："
  echo "   cat ~/.ssh/id_ed25519.pub   # 把输出整行粘贴到 GitHub → Settings → SSH and GPG keys"
  exit 1
fi
echo "✅ SSH 认证通过"

echo ""
echo "[2/4] 检查远程仓库是否存在…"
if ! git ls-remote "$REMOTE" >/dev/null 2>&1; then
  echo "❌ 访问不到 $REMOTE"
  echo "   请先在浏览器里创建这个空仓库（不要勾选 README / .gitignore / license）："
  echo "   https://github.com/new?name=${REPO_NAME}&visibility=public"
  exit 1
fi
echo "✅ 远程仓库可访问"

# ---------- 2. 配置远程并推送 ----------
echo ""
echo "[3/4] 配置远程并推送…"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi
echo "   origin -> $REMOTE"
git push -u origin main

# ---------- 3. 验证 ----------
echo ""
echo "[4/4] 推送完成。接下来 GitHub Actions 会自动运行："
echo "   · 抓取任务：每天北京时间 08:00 自动跑（也可在 Actions 页手动触发）"
echo "   · 首次运行会自动为仓库启用 GitHub Pages，无需进设置页"
echo ""
echo "   站点地址（首次部署约需 1—2 分钟）："
echo "   https://$(echo "$OWNER" | tr '[:upper:]' '[:lower:]').github.io/${REPO_NAME}/"
echo ""
echo "   运行状态可在这里看：https://github.com/${OWNER}/${REPO_NAME}/actions"
