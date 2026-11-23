// 舞台模式（?stage=1）—— 只为"现场 8 分钟"存在，不是给用户用的功能。
//
// 它要解决的三个现场问题（2026-11-23 定）：
//   ① 首访引导浮层会盖住地图，演示机可能是第一次打开这台机器上的浏览器；
//   ② 时间轴会被误触（手放上去、点错一格），帧一漂，讲稿里的数字就对不上；
//   ③ 要演示"点开一条航班 → 证据链"，现场找那一班要花十几秒。
//
// 参数：
//   ?stage=1            开启（与已有的 ?demo=1 不冲突：那个是"离线底图"）
//   &minute=60          固定帧分钟（不写则用默认 60）
//   &flight=NC-0226%23-1 预选班次（航班实例 ID，# 要编码成 %23）
//
// 刻意**不**做：不改数据、不改判据、不隐藏页面内容 —— 只是"少一个能被误触的东西"。

const TRUTHY = new Set(['1', 'true', 'yes', 'on'])

function read() {
  if (typeof window === 'undefined' || !window.location) return { on: false }
  let params
  try {
    params = new URLSearchParams(window.location.search)
  } catch (_) {
    return { on: false }
  }
  const on = TRUTHY.has(String(params.get('stage') || '').toLowerCase())
  if (!on) return { on: false }
  const raw = params.get('minute')
  const minute = raw == null || raw === '' ? null : Number(raw)
  return {
    on: true,
    minute: Number.isFinite(minute) ? Math.max(0, Math.min(1440, Math.round(minute))) : 60,
    flight: (params.get('flight') || '').trim(),
  }
}

export const STAGE = read()

export function isStage() {
  return STAGE.on === true
}
