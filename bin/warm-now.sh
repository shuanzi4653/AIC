#!/usr/bin/env bash
# 一次"把系统叫醒"的预热（V1.1.5）。
#
# 用途：每天 08:05 / 12:05 由 systemd timer 调用，也可以手动跑。
# 与进程内 keep-warm 的分工：keep-warm 只热默认帧（每 15 秒）；本脚本额外打一遍
# 其余关键端点，把模型概率、天气、雷达帧、净空几何都拉起来，并把每一行的耗时打出来 ——
# 出事时这份输出就是"当时哪个端点慢/挂了"的证据。
#
# 原则：**只读**。任何一个端点不 200 就以非 0 退出，但不会去重启服务。
set -u
BASE="${AIC_BASE:-http://127.0.0.1:28083}"
fail=0

probe() {
  local path="$1" name="$2"
  local code time
  read -r code time < <(curl -s -o /dev/null -m 180 -w '%{http_code} %{time_total}' "$BASE$path" || echo "000 0")
  printf '%-26s %-4s %6.2fs\n' "$name" "$code" "$time"
  [ "$code" = "200" ] || fail=1
}

echo "[$(date '+%F %T')] warm start"
probe '/health' 'health'
probe '/traffic/v2/nation?level=nation&minute=60' 'nation(minute=60)'
probe '/traffic/v2/nation/flights?level=nation&minute=60' 'flights(minute=60)'
probe '/traffic/v2/constants' 'constants'
probe '/traffic/v2/overview' 'overview'
probe '/traffic/v2/modelcard' 'modelcard'
probe '/traffic/v2/nation/zones?policy=APPROVAL_REQUIRED' 'zones'
echo "[$(date '+%F %T')] warm done fail=$fail"
exit "$fail"
