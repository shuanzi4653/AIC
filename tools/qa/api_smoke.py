"""V1.1.5 API 全量冒烟 + 功能回归（只读）。"""
import json, urllib.request, urllib.error, urllib.parse, time, sys

B = 'https://tianchuang.shuanzi.site'
PASS, FAIL = [], []

def get(path, timeout=120):
    t0 = time.time()
    try:
        with urllib.request.urlopen(B + path, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}'), round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        body = b''
        try: body = e.read()
        except Exception: pass
        try: return e.code, json.loads(body or b'{}'), round(time.time() - t0, 2)
        except Exception: return e.code, {}, round(time.time() - t0, 2)
    except Exception as e:
        return 'ERR', {'_err': str(e)[:80]}, round(time.time() - t0, 2)

def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  <<< ' + str(detail)[:160]))

def field(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d

print('=== 1. 端点可达性（Java 网关）===')
for name, path in [
    ('health/live', '/api/health/live'),
    ('health/ready', '/api/health/ready'),
    ('traffic/health', '/api/traffic/health'),
    ('v2/overview', '/api/traffic/v2/overview'),
    ('v2/national', '/api/traffic/v2/national'),
    ('v2/nation', '/api/traffic/v2/nation?level=nation&minute=60'),
    ('v2/corridors', '/api/traffic/v2/corridors'),
    ('v2/modelcard', '/api/traffic/v2/modelcard'),
    ('v2/divergences', '/api/traffic/v2/divergences'),
    ('v2/constants', '/api/traffic/v2/constants'),
    ('v2/nation/flights', '/api/traffic/v2/nation/flights?level=nation&minute=60'),
    ('v2/nation/zones', '/api/traffic/v2/nation/zones?policy=APPROVAL_REQUIRED'),
    ('v2/nation/journal', '/api/traffic/v2/nation/journal?minute=60'),
]:
    code, body, dt = get(path)
    check(f'{name} -> 200 ({dt}s)', code == 200, f'code={code} {body.get("_err","")}')

print('=== 2. 四级切片 ===')
lv = {}
for level, ident in [('nation', ''), ('region', 'northeast'), ('province', '辽宁省'), ('city', '沈阳市')]:
    q = urllib.parse.urlencode({'level': level, 'minute': 60, **({'id': ident} if ident else {})})
    code, body, dt = get('/api/traffic/v2/nation?' + q)
    ok = code == 200 and field(body, 'status') == 'OK'
    lv[level] = body
    check(f'{level} 200/OK', ok, code)
    check(f'{level} 有 rollup.total', isinstance(field(body, 'rollup', 'total'), dict), list((body.get('rollup') or {}).keys()))

t_nat = field(lv['nation'], 'rollup', 'total') or {}
t_city = field(lv['city'], 'rollup', 'total') or {}
check('全国 corridors == 492', t_nat.get('corridors') == 492, t_nat.get('corridors'))
check('市层有 airborneDeparting（始发口径）', 'airborneDeparting' in t_city, list(t_city.keys()))
check('市层 airborne >= airborneDeparting（含飞入）',
      (t_city.get('airborne') or 0) >= (t_city.get('airborneDeparting') or 0), t_city)

print('=== 3. 时间轴归一 ===')
_, n0, _ = get('/api/traffic/v2/nation?level=nation&minute=0')
_, n1440, _ = get('/api/traffic/v2/nation?level=nation&minute=1440')
check('minute=0 与 1440 的 traffic 完全一致', n0.get('traffic') == n1440.get('traffic'), [n0.get('traffic'), n1440.get('traffic')])

print('=== 4. 净空两档 ===')
_, zp, _ = get('/api/traffic/v2/nation/zones?policy=PROHIBITED')
_, za, _ = get('/api/traffic/v2/nation/zones?policy=APPROVAL_REQUIRED')
cp = field(zp, 'crossings', 'counts') or {}
ca = field(za, 'crossings', 'counts') or {}
check('两档 forbidden/enterable 互换',
      cp.get('forbidden') == ca.get('enterable') and cp.get('enterable') == ca.get('forbidden'), [cp, ca])
check('几何条数两档相同', cp.get('crossingCorridors') == ca.get('crossingCorridors'), [cp.get('crossingCorridors'), ca.get('crossingCorridors')])

print('=== 5. 判据与绕飞 ===')
_, fl, _ = get('/api/traffic/v2/nation/flights?level=nation&minute=120&virtual=1')
rows = fl.get('flights') or []
det = [r for r in rows if (r.get('detourKm') or 0) > 0]
tiny = [r for r in det if (r.get('detourKm') or 0) < 3]
check('虚拟气象有绕飞班次', len(det) > 0, len(det))
check('无 <3km 的假绕飞', len(tiny) == 0, [r['id'] for r in tiny][:3])
check('绕飞班次 decision 全为 DETOUR', all(r.get('decision') == 'DETOUR' for r in det),
      [(r['id'], r.get('decision')) for r in det][:3])
check('绕飞班次 riskP 未被推过 0.75', all((r.get('riskP') or 0) < 0.75 for r in det),
      [(r['id'], r.get('riskP')) for r in det][:3])
held = [r for r in rows if r.get('decision') == 'HOLD']
# 合法停飞路径有三条：规则分 >=0.75、模型概率 >=0.60、或"压在强回波里且小绕脱不开"（blocked）。
# 第三条是 V1.1.4 加的，label 会写成"停飞（无可用绕飞方案）"。
def hold_ok(r):
    return ((r.get('riskP') or 0) >= 0.75
            or (r.get('pModel') or 0) >= 0.6
            or '无可用绕飞方案' in str(r.get('decisionLabel') or ''))
check('停飞班次三条合法路径之一（规则/模型/绕不开）',
      all(hold_ok(r) for r in held),
      [(r['id'], r.get('riskP'), r.get('pModel'), r.get('decisionLabel')) for r in held if not hold_ok(r)][:3])

print('=== 6. 取证链 ===')
if rows:
    fid = rows[0]['id']
    _, ev, _ = get('/api/traffic/v2/nation/evidence?flight=' + urllib.parse.quote(fid) + '&minute=120&virtual=1')
    steps = ev.get('steps') or []
    check(f'evidence({fid}) 五步', len(steps) == 5, len(steps))
    srcs = {row.get('source') for s in steps for row in (s.get('rows') or [])}
    check('每行都有来源标注', srcs <= {'SIM', 'PUBLIC', 'DERIVED', 'OFFICIAL', 'ABSENT'} and len(srcs) > 0, srcs)

print('=== 7. 参数校验 ===')
for path, want, name in [
    ('/api/traffic/v2/nation?level=nation&minute=1441', 422, 'minute 超界 422'),
    ('/api/traffic/v2/nation?level=galaxy', 422, 'level 非法 422'),
    ('/api/traffic/v2/nation?level=city&id=%E7%81%AB%E6%98%9F%E5%B8%82', 404, '城市不存在 404'),
    ('/api/traffic/v2/nation/zones?policy=WHATEVER', 422, 'policy 非法 422'),
    ('/api/traffic/v2/nation/evidence?flight=NC-9999%239&minute=60', 404, '班次不存在 404'),
    ('/api/traffic/v2/nope', 404, '未知资源 404'),
]:
    code, body, dt = get(path)
    check(name, code == want, f'code={code}')

print('=== 8. 缓存协商 ===')
req = urllib.request.Request(B + '/api/traffic/v2/nation?level=nation&minute=60')
with urllib.request.urlopen(req, timeout=120) as r:
    etag = r.headers.get('ETag'); cc = r.headers.get('Cache-Control'); r.read()
check('nation 有 ETag', bool(etag), etag)
check('nation 有 Cache-Control', bool(cc), cc)
req2 = urllib.request.Request(B + '/api/traffic/v2/nation?level=nation&minute=60', headers={'If-None-Match': etag or ''})
try:
    with urllib.request.urlopen(req2, timeout=120) as r:
        code2 = r.status; n = len(r.read())
    check('If-None-Match 命中 304', code2 == 304, code2)
except urllib.error.HTTPError as e:
    check('If-None-Match 命中 304', e.code == 304, e.code)

print('=== 9. 静态与合规 ===')
# 必须**不跟随**重定向：urllib 默认跟随，301 会被吃成 200，看起来像"跳转没生效"。
NO_REDIRECT = urllib.request.build_opener(urllib.request.HTTPHandler)
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
NO_REDIRECT = urllib.request.build_opener(_NoRedirect)
for path, want, name in [('/', 200, '首页 200'), ('/assets/beian.png', 200, '备案图标 200'),
                         ('/favicon.ico', 204, 'favicon 204'), ('/beian.png', 301, 'beian 301'),
                         ('/build-info.json', 200, 'build-info 200')]:
    try:
        with NO_REDIRECT.open(B + path, timeout=30) as r:
            code = r.status; r.read()
    except urllib.error.HTTPError as e:
        code = e.code
    check(name, code == want, code)

print(f'\n==== 合计 PASS {len(PASS)} / FAIL {len(FAIL)} ====')
if FAIL:
    print('失败项：', FAIL)
sys.exit(1 if FAIL else 0)
