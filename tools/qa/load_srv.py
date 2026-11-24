"""服务器内部压测 + 1 分钟浸泡（只读）。在云端 /tmp 跑，绕开公网带宽。"""
import json, ssl, statistics, subprocess, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE = 'https://tianchuang.shuanzi.site'
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

MIX = [
    ('/api/traffic/v2/nation?level=nation&minute=60', 5),
    ('/api/traffic/v2/nation/flights?level=nation&minute=90', 3),
    ('/api/traffic/v2/overview', 1),
    ('/api/traffic/v2/nation/zones?policy=APPROVAL_REQUIRED', 1),
]
PATHS = [p for p, w in MIX for _ in range(w)]

def hit(path, timeout=120):
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + path)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0
    except Exception:
        return 'ERR', time.time() - t0

def rss(unit):
    out = subprocess.run(['systemctl', 'show', unit, '-p', 'MemoryCurrent'],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out.split('=')[1]) // (1024 * 1024)
    except Exception:
        return -1

def cpu(unit):
    out = subprocess.run(['systemctl', 'show', unit, '-p', 'CPUUsageNSec'],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out.split('=')[1]) / 1e9
    except Exception:
        return -1.0

def stat(name, lat, errs, extra=''):
    lat = sorted(lat)
    if not lat:
        print(f'{name}: 全部失败 errs={errs}')
        return
    p = lambda q: lat[min(len(lat) - 1, int(len(lat) * q))]
    print(f'{name}: n={len(lat)} 错误={errs} '
          f'p50={statistics.median(lat):.3f}s p95={p(0.95):.3f}s max={lat[-1]:.3f}s {extra}')

print('=== A. 梯度并发（每档 20 请求，混合端点）===')
for conc in (2, 4, 8, 16):
    batch = [PATHS[i % len(PATHS)] for i in range(20)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        res = list(ex.map(hit, batch))
    wall = time.time() - t0
    lat = [d for c, d in res if c == 200]
    errs = len(res) - len(lat)
    stat(f'并发 {conc:2d}', lat, errs, f'总墙钟={wall:.2f}s 吞吐={len(res)/wall:.1f} rps')

print('=== B. 1 分钟浸泡（5 rps 目标，混合端点）===')
stop = threading.Event()
samples = []

def sampler():
    while not stop.is_set():
        samples.append((time.time(), rss('AIC-tianchuang'), rss('AIC-tianchuang-python'),
                        cpu('AIC-tianchuang-python')))
        stop.wait(10)

th = threading.Thread(target=sampler, daemon=True); th.start()
rss_start = (rss('AIC-tianchuang'), rss('AIC-tianchuang-python'))
lat, errs, sent = [], 0, 0
t_start = time.time()
with ThreadPoolExecutor(max_workers=4) as ex:
    futures = []
    while time.time() - t_start < 60:
        for _ in range(5):
            futures.append(ex.submit(hit, PATHS[sent % len(PATHS)]))
            sent += 1
        time.sleep(1)
    for f in futures:
        c, d = f.result()
        if c == 200: lat.append(d)
        else: errs += 1
stop.set(); th.join(timeout=3)

stat('浸泡 60s', lat, errs, f'目标 300 请求，实发 {sent}')
print('  RSS(MB) 起: java=%s python=%s' % rss_start)
if samples:
    print('  采样(相对秒, javaMB, pyMB, pyCPU累计s):')
    base = samples[0][0]
    for t, a, b, c in samples:
        print(f'    {t-base:5.1f}  {a:5d}  {b:5d}  {c:8.1f}')
    first, last = samples[0], samples[-1]
    print(f'  RSS 变化: java {last[1]-first[1]:+d} MB, python {last[2]-first[2]:+d} MB')
    print(f'  Python CPU 累计增量: {last[3]-first[3]:.1f} s / {last[0]-first[0]:.0f} s 窗口')
