/**
 * V1.1.4 · 绕飞与裁决的展示口径（4 条）。
 *
 * 2026-11-24 用户报「黄石—九江这条应该是绕飞，为什么还是禁止」。查到的是三处口径：
 *   ① 详情标签写的是裁决，颜色却按 riskLevel 染 —— "绕飞放行"被涂成红底，读起来就是禁止；
 *   ② 地图航迹同理，琥珀（绕飞）与红（停飞）都用 riskLevel 判，一架飞机会同时显示两种含义；
 *   ③ 航线悬停把 borderBlocked（边界越界被剔）写成"停飞"，和"绕飞/直飞"并列。
 * 后端那条「绕飞不该加分」在 backend-python/tests/test_detour_verdict.py 里。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
const PANEL = read('../src/components/traffic/NationPanel.vue')
const MAP = read('../src/components/traffic/NationMap.vue')
const OPS = read('../../backend-python/traffic/nation_ops.py')

test('详情标签的颜色跟裁决走，不跟风险档走', () => {
  const line = PANEL.split('\n').find(l => l.includes('class="tag"') && l.includes('decisionLabel'))
  assert.ok(line, '找不到详情标签那一行')
  assert.ok(line.includes("selectedFlight.decision==='HOLD'"), '标签颜色必须按 decision 判')
  assert.ok(!line.includes('selectedFlight.riskLevel'), '标签颜色不能再按 riskLevel 判，否则绕飞放行会被染红')
})

test('地图航迹：琥珀=绕飞、红=停飞，都按 decision', () => {
  const line = MAP.split('\n').find(l => l.includes('detour:') && l.includes('bad:'))
  assert.ok(line, '找不到航迹配色那一行')
  assert.ok(line.includes("detour:f.decision==='DETOUR'"), '绕飞配色要按 decision')
  assert.ok(line.includes("bad:f.decision==='HOLD'"), '停飞配色要按 decision')
  assert.ok(!line.includes('riskLevel'), '不能再按 riskLevel 染，否则"在绕"和"禁飞"同时成立')
})

test('航线悬停不再把边界封锁写成停飞', () => {
  assert.ok(!MAP.includes("line.blocked?'停飞'"), 'borderBlocked 是越界封锁，不是天气停飞')
  assert.ok(MAP.includes('越界封锁'), '要明确写成"越界封锁（不纳入）"')
})

test('后端：绕飞不再给风险分加成', () => {
  assert.ok(!OPS.includes('risk + 0.18'), '绕飞是处置不是风险源，+0.18 会把"提示"推到停飞')
  assert.ok(OPS.includes('绕飞是**处置**'), '注释要说明为什么不再加分，否则下一个人会加回去')
})
