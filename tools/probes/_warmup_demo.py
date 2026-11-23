"""演示前预热：把四个页面用到的载荷按顺序跑一遍，让缓存热起来。

为什么需要它：首次请求要建全国载荷（冷启动实测 20–30 秒，虚拟帧最慢 171 秒），
现场"点一下等 20 秒"看起来就像页面坏了（2026-11-23 复核）。预热把这段耗时提前吃掉。

用法（服务已启动，默认走本机网关 8085）：

    python tools/probes/_warmup_demo.py
    python tools/probes/_warmup_demo.py --base http://127.0.0.1:8085 --minute 60

判据：四行全是 200，且总耗时打印出来。任何一行失败会重试一次，仍失败则退出码 1 ——
演示前跑一次，红了就别上台。
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def get(url, timeout):
    started = time.perf_counter()
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, body, time.perf_counter() - started


def call(label, url, timeout, retries=1):
    last = ''
    for attempt in range(retries + 1):
        try:
            status, body, cost = get(url, timeout)
            size = len(body)
            try:
                doc = json.loads(body.decode('utf-8'))
            except Exception:
                doc = {}
            note = ''
            if isinstance(doc, dict):
                if doc.get('status') and doc.get('status') != 'OK':
                    note = ' status=%s' % doc.get('status')
                elif doc.get('available') is False:
                    note = ' available=false'
            print('%-14s %3d  %6.2fs  %8.1f KB%s' % (label, status, cost, size / 1024.0, note))
            return status, doc
        except urllib.error.HTTPError as exc:
            last = 'HTTP %s' % exc.code
        except Exception as exc:  # noqa: BLE001 - 预热脚本要把原因原样打出来
            last = '%s: %s' % (type(exc).__name__, exc)
        if attempt < retries:
            print('%-14s FAIL (%s) · 重试' % (label, last))
            time.sleep(1.0)
    print('%-14s FAIL %s' % (label, last))
    return 0, {}


def pick_flight(doc):
    """取一条真实班次 id 用于取证链预热；没有就返回 None（不阻断其余预热）。"""
    for key in ('flights', 'items'):
        rows = doc.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get('id'):
                    return str(row['id'])
    return None


def main():
    ap = argparse.ArgumentParser(description='演示前预热全国层四个载荷')
    ap.add_argument('--base', default='http://127.0.0.1:8085')
    ap.add_argument('--minute', type=int, default=60)
    ap.add_argument('--timeout', type=float, default=120.0)
    ap.add_argument('--city', default='沈阳市', help='顺带预热的城市层（留空跳过）')
    args = ap.parse_args()

    base = args.base.rstrip('/') + '/api/traffic/v2'
    minute = max(0, min(1440, args.minute))
    started = time.perf_counter()
    failures = 0

    status, _ = call('health', base.rsplit('/api', 1)[0] + '/api/health/live', args.timeout)
    failures += 0 if status == 200 else 1

    status, nation = call('nation', '%s/nation?level=nation&minute=%d' % (base, minute), args.timeout)
    failures += 0 if status == 200 else 1

    status, flights = call('flights', '%s/nation/flights?level=nation&minute=%d' % (base, minute),
                           args.timeout)
    failures += 0 if status == 200 else 1

    flight_id = pick_flight(flights) or pick_flight(nation)
    if flight_id:
        quoted = urllib.parse.quote(flight_id, safe='')
        status, _ = call('evidence', '%s/nation/evidence?flight=%s&minute=%d' % (base, quoted, minute),
                         args.timeout)
        failures += 0 if status == 200 else 1
    else:
        print('%-14s SKIP 没有班次 id' % 'evidence')

    status, _ = call('constants', '%s/constants' % base, args.timeout)
    failures += 0 if status == 200 else 1

    if args.city:
        quoted_city = urllib.parse.quote(args.city, safe='')
        status, _ = call('city', '%s/nation?level=city&id=%s&minute=%d' % (base, quoted_city, minute),
                         args.timeout)
        failures += 0 if status == 200 else 1

    print('---- 总耗时 %.2fs，失败 %d 项' % (time.perf_counter() - started, failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
