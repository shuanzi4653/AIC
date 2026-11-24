/**
 * V1.1.5 · 审计修复的护栏（6 条）。
 *
 * 每一条都对应 docs/压力测试与缺陷清单-20261124.md 里的一处实测缺陷，
 * 用"某段写法在不在"钉住，避免下次改回去。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs'

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
const NATION = read('../../backend-python/traffic/nation.py')
const MAIN = read('../../backend-python/main.py')
const V2 = read('../../backend-python/traffic/v2.py')
const RUNTIME = read('../src/traffic/runtime.js')
const PANEL = read('../src/components/traffic/NationPanel.vue')
const PY_CLIENT = read('../../backend-java/src/main/java/com/tianchuang/service/PythonClient.java')

test('P1-4 时间轴 1440 与 0 归一为同一帧', () => {
  assert.ok(NATION.includes('def _norm_minute('), '缺少 _norm_minute')
  assert.ok(NATION.includes('% 1440'), '归一必须取模 1440')
  // 三个高频入口都要走归一，漏一个就会出现"整点前一格与整点不等"
  for (const fn of ['def payload(', 'def flights_payload(', 'def evidence(']) {
    const at = NATION.indexOf(fn)
    assert.ok(at > 0, `找不到 ${fn}`)
    const body = NATION.slice(at, at + 400)
    assert.ok(body.includes('_norm_minute('), `${fn} 没有归一 minute`)
  }
})

test('P1-2 市层在飞含飞入，同时保留始发口径', () => {
  assert.ok(NATION.includes("inbound = [f for f in flights if f.get('toName') == name"),
    '缺少 inbound 统计')
  assert.ok(NATION.includes("'airborneDeparting'"), '缺少始发口径（用于与上层对账）')
  assert.ok(NATION.includes('touch = origin + inbound'), '在飞应含飞入')
  assert.ok(PANEL.includes('airborneDeparting'), '界面要说明含飞入口径')
})

test('P1-1 载荷走缓存 + single-flight', () => {
  assert.ok(NATION.includes('_PAYLOAD_TTL'), '缺少缓存 TTL')
  assert.ok(NATION.includes('def _single_flight('), '缺少 single-flight')
  assert.ok(NATION.includes('_PAYLOAD_CACHE'), '缺少载荷缓存')
  const at = NATION.indexOf('def payload(')
  assert.ok(NATION.slice(at, at + 400).includes('_single_flight('), 'payload 没走 single-flight')
})

test('P1-3 浏览器不再直连第三方瓦片（CORS 决定它必然失败）', () => {
  assert.ok(RUNTIME.includes('RADAR_RELAY_VIA_BROWSER = false'), '必须显式关闭')
  const at = RUNTIME.indexOf('export function radarRelayReady(')
  assert.ok(RUNTIME.slice(at, at + 300).includes('RADAR_RELAY_VIA_BROWSER'), '函数要先看开关')
})

test('P2-3 ETag + 304：Python 发头，Java 原样转出', () => {
  assert.ok(MAIN.includes('def _conditional_json('), '缺少 _conditional_json')
  assert.ok(MAIN.includes("'ETag'"), '没有 ETag 头')
  assert.ok(MAIN.includes('if-none-match'), '没有按 If-None-Match 判 304')
  assert.ok(PY_CLIENT.includes('statusCode() == 304'), 'Java 没处理 304，会掉进 readValue 抛 500')
})

test('P2-2 模型卡写清作用域并给全国模型段', () => {
  assert.ok(V2.includes("'scope'"), '缺少 scope 说明')
  assert.ok(V2.includes('def _national_model_doc('), '缺少全国模型段')
  assert.ok(V2.includes('ml-v3-national-vis.json'), '全国段要读 v3 元数据')
})

test('P2-1 frontend/src 下不得再出现 Java 源码', () => {
  const root = new URL('../src/', import.meta.url)
  const offenders = []
  const walk = dir => {
    for (const name of readdirSync(dir)) {
      const full = new URL(name, dir)
      const st = statSync(full)
      if (st.isDirectory()) walk(new URL(name + '/', dir))
      else if (name.endsWith('.java')) offenders.push(full.pathname)
    }
  }
  if (existsSync(root)) walk(root)
  assert.deepEqual(offenders, [], `frontend/src 下有 Java 源码：${offenders.slice(0, 3).join(', ')}`)
})
