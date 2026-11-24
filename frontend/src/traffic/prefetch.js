/**
 * 打开页面就自动预热（V1.1.6）。
 *
 * 背景：`tools/probes/_warmup_demo.py` 得有人手动跑，而"人什么时候打开页面"是不确定的。
 * 这个模块把那套顺序搬进浏览器：首屏渲染完 4 秒后，静默按 轻→重 的顺序把下面几样拉一遍，
 * 用户点到哪一块都已经是热的。
 *
 * 三条克制：
 *   ① **只在空闲时跑**：`load` 之后 4 秒才启动，绝不和地图/主载荷抢连接；
 *   ② **全部静默**：任一请求失败都不弹提示、不进控制台错误、不影响页面，
 *      因为预热的失败本来就是"没热成"，不是"功能坏了"；
 *   ③ **一个标签页只跑一次**：sessionStorage 打标，刷新另算。
 *
 * 顺序是有讲究的（与 `_warmup_demo.py` 同一套）：常量 → 总览 → 班次列表 →
 * 挑一个在飞班次的取证链 → 反事实预建。前三步是"用户一定会碰到的"，
 * 反事实最后跑且走的是 POST 预建（后台建场，不占前端超时）。
 */
import { requestJson } from '../api.js'

const MARK = 'alc.prefetch.v1'
let started = false

function done() {
  try { return sessionStorage.getItem(MARK) === '1' } catch (_) { return false }
}
function markDone() {
  try { sessionStorage.setItem(MARK, '1') } catch (_) { /* 隐私模式下无所谓 */ }
}

const warm = (path, ms = 15_000) => requestJson(path, { timeoutMs: ms }).catch(() => null)

async function go() {
  // 1) 阈值常量：所有判据页都要读它，最轻
  await warm('/api/traffic/v2/constants', 8_000)
  // 2) 全国总览：台账/成效页的第一屏
  await warm('/api/traffic/v2/overview', 20_000)
  // 3) 班次列表；顺手拿一个在飞班次，把它的取证链也热掉（推演页必点的就是它）
  const flights = await warm('/api/traffic/v2/nation/flights?level=nation&minute=60', 20_000)
  const first = flights && Array.isArray(flights.flights) ? flights.flights[0] : null
  if (first && first.id) {
    await warm('/api/traffic/v2/nation/evidence?flight=' + encodeURIComponent(first.id) + '&minute=60', 20_000)
  }
  // 4) 反事实：POST 预建，后端起后台线程建场，这里立刻返回，不等 40–90 秒
  await requestJson('/api/traffic/v2/counterfactual/prewarm?seed=42&scenario=live', {
    method: 'POST',
    timeoutMs: 10_000,
  }).catch(() => null)
  markDone()
}

export function runPrefetch() {
  if (started || done()) return
  started = true
  const kick = () => setTimeout(() => { go().catch(() => null) }, 4_000)
  if (document.readyState === 'complete') kick()
  else window.addEventListener('load', kick, { once: true })
}
