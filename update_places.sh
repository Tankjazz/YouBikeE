#!/bin/zsh
# 更新「我的地點」：把 Takeout zip 轉成加密的 places.enc，然後發布
# 用法：./update_places.sh ~/Downloads/takeout-xxxx.zip
set -e
cd "$(dirname "$0")"
ZIP="${1:-$(ls -t ~/Downloads/takeout-*.zip 2>/dev/null | head -1)}"
[ -f "$ZIP" ] || { echo "找不到 Takeout zip，請給路徑"; exit 1; }
echo "使用：$ZIP"
read -s "PW?請輸入地點加密密碼（手機解鎖時要輸入同一組）："; echo
python3 tools/build_places.py "$ZIP" --password "$PW"
./deploy.sh
