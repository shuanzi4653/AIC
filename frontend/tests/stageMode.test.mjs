/**
 * V1.1.3 · 舞台模式与证据卡的两条判据。
 *
 * 这两块是给现场用的：`?stage=1` 钉帧、不弹引导；证据链要能"带走"（纯文本 / PNG）。
 * 它们都不依赖 vue，所以能在这里真跑，而不是只做字符串断言。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { digestText } from '../src/traffic/evidenceCard.js'

const EVIDENCE = {
  status: 'OK',
  generatedAt: '2026-11-23T04:00:00Z',
  virtual: false,
  flight: {
    id: 'NC-0226#-1', callsign: 'TC0226', fromName: '沈阳市', toName: '大连市',
    decisionLabel: '暂不放行', riskP: 0.71, riskLevelLabel: '高风险',
  },
  steps: [
    { n: 1, title: '班次与航路', rows: [{ label: '航线', value: 'NC-0226', source: 'SIM' }] },
    { n: 2, title: '端点实况', rows: [{ label: '能见度', value: '1200 m', source: 'PUBLIC' }] },
    { n: 3, title: '航路回波', rows: [{ label: '最强回波', value: '38 dBZ', source: 'PUBLIC' }] },
    { n: 4, title: '风险与裁决', rows: [{ label: '概率', value: '71%', source: 'DERIVED' }] },
    { n: 5, title: '反事实与边界', rows: [{ label: '直飞暴露', value: '12 min', source: 'DERIVED' }] },
  ],
  conclusion: '暂不放行：风险 0.71；能见度低于门槛',
  discipline: '本链为「规则派生」，不是官方管制结论。',
}

test('证据卡文本：一行一个事实，五步与来源都在', () => {
  const text = digestText(EVIDENCE)
  const lines = text.split('\n')
  assert.ok(lines[0].includes('TC0226') && lines[0].includes('沈阳市'), '首行没有班次与航线')
  for (const n of [1, 2, 3, 4, 5]) {
    assert.ok(text.includes(`${n}. `), `缺少第 ${n} 步`)
  }
  assert.ok(text.includes('(PUBLIC)'), '行尾没有带来源')
  assert.ok(text.includes('结论：'), '缺少结论行')
  assert.ok(text.includes('纪律：'), '缺少纪律声明')
  assert.ok(!digestText({ status: 'NOT_FOUND' }), '非 OK 的证据不该产出文本')
})

test('舞台模式：只认 ?stage=1，并解析帧与班次', async () => {
  const prev = globalThis.window
  try {
    globalThis.window = { location: { search: '?stage=1&minute=90&flight=NC-0226%23-1' } }
    const mod = await import('../src/traffic/stageMode.js?case=on')
    assert.equal(mod.isStage(), true)
    assert.equal(mod.STAGE.minute, 90)
    assert.equal(mod.STAGE.flight, 'NC-0226#-1')

    globalThis.window = { location: { search: '?demo=1' } }
    const off = await import('../src/traffic/stageMode.js?case=off')
    assert.equal(off.isStage(), false, '?demo=1 是离线底图那个开关，不该被当成舞台模式')

    globalThis.window = { location: { search: '?stage=1&minute=9999' } }
    const clamp = await import('../src/traffic/stageMode.js?case=clamp')
    assert.equal(clamp.STAGE.minute, 1440, '帧没有夹到 0–1440')
  } finally {
    if (prev === undefined) delete globalThis.window
    else globalThis.window = prev
  }
})
