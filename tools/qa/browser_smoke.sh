#!/usr/bin/env bash
# 11 条前端路由冒烟：抓 console 错误 + 检查渲染异常文案
EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
BASE="https://tianchuang.shuanzi.site/#"
ROUTES="situation/home situation/national situation/overview situation/weather corridor/profile dispatch/console dispatch/ledger dispatch/evidence model/card model/reference compare/log"
fail=0
for r in $ROUTES; do
  log="/tmp/bs-$(echo $r | tr '/' '-').log"
  dom="/tmp/bs-$(echo $r | tr '/' '-').html"
  "$EDGE" --headless=new --disable-gpu --user-data-dir=/tmp/edgebs --enable-logging=stderr --v=0 \
    --virtual-time-budget=9000 --dump-dom "$BASE/$r" >"$dom" 2>"$log"
  size=$(stat -c%s "$dom" 2>/dev/null | head -1); size=${size:-0}
  err=$(grep -cE "CONSOLE.*(Uncaught|TypeError|ReferenceError|is not a function|blocked by CORS)" "$log" 2>/dev/null | head -1); err=${err:-0}
  bad=$(grep -oE "undefined|NaN|\[object Object\]" "$dom" 2>/dev/null | sort | uniq -c | tr '\n' ' ')
  top=$(grep -c "data-workbench-top" "$dom" 2>/dev/null | head -1); top=${top:-0}
  if [ "$top" -ge 1 ] && [ "$err" -eq 0 ] && [ -z "$bad" ]; then
    printf "%-22s OK   dom=%7s  console_err=0\n" "$r" "$size"
  else
    printf "%-22s FAIL dom=%7s  console_err=%s  bad='%s'  top=%s\n" "$r" "$size" "$err" "$bad" "$top"
    fail=1
  fi
done
echo "---- browser smoke fail=$fail ----"
exit $fail
