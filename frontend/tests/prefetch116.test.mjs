/**
 * V1.1.6 · 打开页面就预热 + 反事实预建（4 条）。
 *
 * 这一版只做两件事，都围绕"别让用户等"：
 *   ① 把 `tools/probes/_warmup_demo.py` 的顺序搬进浏览器（首屏空闲后静默跑一遍）；
 *   ② 反事实页首次要建场 40–90 秒 —— 进页面就发一个 POST 预建，后端起后台线程建。
 * 用源码断言钉住"开关还在、顺序没被改乱、预建没退化成同步阻塞"。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
const MAIN = read('../../backend-python/main.py')
const CTRL = read('../../backend-java/src/main/java/com/tianchuang/controller/DecisionController.java')
const PREFETCH = read('../src/traffic/prefetch.js')
const WB = read('../src/components/TrafficWorkbench.vue')

test('后端：反事实预建是 POST + 后台线程 + 60 秒节流', () => {
  assert.ok(MAIN.includes("@app.post('/traffic/v2/counterfactual/prewarm')"), '缺少预建端点')
  assert.ok(MAIN.includes('_CF_PREWARM_SECONDS'), '缺少节流常量')
  assert.ok(MAIN.includes('THROTTLED'), '节流命中要有明确状态，不能假装在跑')
  const at = MAIN.indexOf("def traffic_v2_counterfactual_prewarm")
  const body = MAIN.slice(at, at + 1800)
  assert.ok(body.includes('Thread(target=build'), '预建必须丢到后台线程，否则请求线程被占 90 秒')
  assert.ok(body.includes("status': 'READY'") || body.includes('"READY"') || body.includes("'READY'"),
    '已就绪时应直接返回 READY，不要重复建')
})

test('Java：预建走 POST 白名单（否则前端 405）', () => {
  assert.ok(CTRL.includes('@PostMapping("/traffic/v2/counterfactual/prewarm")'), '缺少 POST 转发')
  const at = CTRL.indexOf('counterfactualPrewarm')
  assert.ok(CTRL.slice(at, at + 600).includes('Map.of()'), '必须给非 null body，否则 decisionRequest 会走 GET 分支')
})

test('前端：预热顺序与克制（空闲启动 / 静默 / 一次）', () => {
  assert.ok(PREFETCH.includes('const MARK'), '缺少"一次"标记')
  assert.ok(PREFETCH.includes('sessionStorage'), '标记要落在 sessionStorage，刷新另算')
  assert.ok(PREFETCH.includes('setTimeout'), '必须延迟启动，别和首屏抢连接')
  // 顺序：constants → overview → flights → evidence → prewarm
  const order = ['constants', 'overview', 'nation/flights', 'nation/evidence', 'counterfactual/prewarm']
  let cursor = -1
  for (const key of order) {
    const idx = PREFETCH.indexOf(key)
    assert.ok(idx > cursor, `预热顺序被改了：${key} 应在前一项之后`)
    cursor = idx
  }
  assert.ok(PREFETCH.includes('catch(() => null)'), '预热失败必须静默，不能弹错')
})

test('前端：页面挂载时调用预热', () => {
  assert.ok(WB.includes("from '../traffic/prefetch.js'"), 'TrafficWorkbench 没引入 prefetch')
  assert.ok(WB.includes('runPrefetch()'), '挂载点没有调用 runPrefetch')
})
