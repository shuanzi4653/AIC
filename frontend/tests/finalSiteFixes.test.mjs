/**
 * V1.1.3 · 总决赛现场版的四条判据。
 *
 * 这一版没有新功能，只有三处"线上会被当成坏了"的口径与交互：
 *   · 市层台账的合计按省算（同一行两个口径）；
 *   · 净空两档切了以后数字一模一样（读起来像没生效）；
 *   · 反事实的案例分支一进页面就自动重跑计划，超时重试 40 次、没有可停的按钮。
 *
 * 为什么用源码字符串断言而不是渲染测试：`node --test` 这一套不装 vue，
 * 组件跑不起来；而这三条的判据本身就是"某段写法在不在"，字符串够了。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
const NATION = read('../../backend-python/traffic/nation.py')
const ZONES = read('../../backend-python/traffic/nation_zones.py')
const PANEL = read('../src/components/traffic/NationPanel.vue')
const BRIEF = read('../src/components/traffic/NationBriefing.vue')
const CF = read('../src/components/traffic/CounterfactualPanel.vue')
const VERSION = read('../../VERSION').trim()
const PKG = JSON.parse(read('../package.json'))

test('市层合计只按本市算，不再回省级块', () => {
  assert.ok(NATION.includes('def _city_totals('), '缺少 _city_totals')
  // 注意：`elif level == 'city':` 也包含 "if level == 'city':" 这个子串，
  // 所以要带换行与缩进定位，否则会切到 _flights_payload_locked 的那一支上去（第一版就这么假红）。
  const start = NATION.indexOf("\n    if level == 'city':")
  const end = NATION.indexOf("return {'status': 'INVALID'", start)
  assert.ok(start > 0 && end > start, '没定位到 _payload_locked 的市层分支')
  const cityBranch = NATION.slice(start, end)
  assert.ok(cityBranch.includes('_city_totals('), '市层分支仍在用省口径的 _totals')
  assert.ok(!cityBranch.includes('province_blocks('), '市层分支还调用了 province_blocks')
  assert.ok(/lowVisCities/.test(NATION.slice(NATION.indexOf('def _city_totals('),
                                NATION.indexOf('def _totals('))), '_city_totals 没给 lowVisCities')
})

test('净空两档有两个不同的数：可申请与禁止随 policy 互换', () => {
  assert.ok(ZONES.includes("'enterable'"), 'crossings 没有 enterable')
  assert.ok(ZONES.includes("'forbidden'"), 'crossings 没有 forbidden')
  assert.ok(/enterable'\s*:\s*0 if strict else hit_count/.test(ZONES), 'enterable 未随 policy 归零')
  assert.ok(/forbidden'\s*:\s*hit_count if strict else 0/.test(ZONES), 'forbidden 未随 policy 计数')
  // 界面必须读这两个字段，而不是继续只读 hit
  assert.ok(PANEL.includes('counts.forbidden') && PANEL.includes('counts.enterable'),
    '空域侧栏仍只读 hit')
  assert.ok(BRIEF.includes('counts?.forbidden') || BRIEF.includes('counts?.enterable'),
    '情报页的净空行仍只读 hit')
})

test('案例重放不再自动开跑：显式开始 + 有上限 + 可中止', () => {
  assert.ok(!/onMounted\(\(\)=>\{polls=0;load\(\)\}\)/.test(CF), '案例分支还在挂载即发请求')
  assert.ok(/if\(!effectiveCase\.value\)load\(\)/.test(CF), 'onMounted 没有按模式分流')
  assert.ok(/if\(!caseArmed\.value\)return/.test(CF), 'load 没有"未开始就不发请求"的闸')
  const cap = Number((CF.match(/const MAX_POLLS=(\d+)/) || [])[1])
  assert.ok(Number.isFinite(cap) && cap <= 10, `重试上限仍是 ${cap} 次`)
  assert.ok(/Math\.pow\(1\.7/.test(CF), '重试仍是固定间隔（没有退避）')
  assert.ok(CF.includes('abortWait'), '没有"停止等待"')
  assert.ok(CF.includes('data-cf-armed'), '没有"显式开始"的入口块')
})

test('版本号 1.1.3 五处一致', () => {
  assert.equal(VERSION, '1.1.3')
  assert.equal(PKG.version, '1.1.3')
  const POM = read('../../backend-java/pom.xml')
  assert.ok(POM.includes('<version>1.1.3</version>'), 'pom.xml 没跟上')
  const LOCK = JSON.parse(read('../package-lock.json'))
  assert.equal(LOCK.version, '1.1.3')
  assert.equal(LOCK.packages[''].version, '1.1.3')
})
