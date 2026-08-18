#!/bin/zsh
# 一鍵發布到 GitHub Pages（第一次會建 repo；之後只推更新）
set -e
cd "$(dirname "$0")"
git add -A
git commit -m "update $(date '+%Y-%m-%d %H:%M')" || true
if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create YouBikeE --public --source=. --push --description "電輔車在哪：YouBike 2.0E 即時地圖 PWA"
  gh api -X POST repos/Tankjazz/YouBikeE/pages -f 'source[branch]=main' -f 'source[path]=/' >/dev/null
else
  git push
fi
echo "網址：https://tankjazz.github.io/YouBikeE/  （第一次要等 1～2 分鐘）"
