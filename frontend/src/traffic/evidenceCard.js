// 证据链的"能带走"版本：一份纯文本 + 一张图。
//
// 为什么需要：答辩 PPT 的 P5 要用真实截图（不是示意图），而现场截屏有三个坑 ——
// 分辨率不够、卡片被侧栏截断、时间戳读不清。这里用同一份证据 JSON 直接排一张
// 1600 宽的卡片，图上的数字与页面**同源**，不存在"截图时手抖拿错帧"。
//
// 为什么不引 html2canvas：多一个依赖就多一次"现场白屏"的机会，而这里要画的东西
// 只有矩形与文字，canvas 的 fillText 足够，且不依赖任何库。

const FONT = '"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif'
const MONO = 'Consolas,"Courier New",monospace'

const COLOR = {
  bg: '#0b1a2b',
  panel: '#12283f',
  line: '#2c4a60',
  text: '#e6f2fb',
  quiet: '#9db6c8',
  accent: '#5cdbff',
  watch: '#ffb547',
}

function safe(v) {
  return v == null ? '—' : String(v)
}

/** 证据链 → 纯文本（可直接粘进答辩备注）。每行一个事实，不写形容词。 */
export function digestText(ev) {
  if (!ev || ev.status !== 'OK') return ''
  const f = ev.flight || {}
  const lines = []
  lines.push(`班次 ${safe(f.callsign)}（${safe(f.id)}） ${safe(f.fromName)} → ${safe(f.toName)}`)
  lines.push(`裁决 ${safe(f.decisionLabel)} · 风险 ${safe(f.riskP)} · 等级 ${safe(f.riskLevelLabel)}`)
  lines.push(`时基 ${safe(ev.generatedAt)}${ev.virtual ? ' · 虚拟气象' : ''}`)
  for (const step of ev.steps || []) {
    const parts = (step.rows || []).map(row => `${row.label}=${row.value}${row.source ? '(' + row.source + ')' : ''}`)
    lines.push(`${step.n}. ${step.title}：${parts.join('；')}`)
  }
  lines.push(`结论：${safe(ev.conclusion)}`)
  if (ev.discipline) lines.push(`纪律：${ev.discipline}`)
  return lines.join('\n')
}

/** 证据链 → PNG（1600 宽，深色底，与界面同色系）。 */
export function drawEvidenceCard(ev, opts = {}) {
  const width = opts.width || 1600
  const pad = 48
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  const bodyWidth = width - pad * 2

  const rows = []
  const push = (kind, text, extra) => rows.push({ kind, text, extra })

  const f = ev?.flight || {}
  push('title', `${safe(f.callsign)} · ${safe(f.fromName)} → ${safe(f.toName)}`)
  push('meta', `班次 ${safe(f.id)} · ${safe(f.decisionLabel)} · 风险 ${safe(f.riskP)} · ${safe(ev?.generatedAt)}`)
  for (const step of ev?.steps || []) {
    push('step', `${step.n}. ${step.title}`)
    for (const row of step.rows || []) {
      push('row', `${row.label}：${row.value}`, row.source)
    }
  }
  push('gap', '')
  push('conclusion', safe(ev?.conclusion))
  if (ev?.discipline) push('foot', ev.discipline)

  // 先量后画：两遍排版，避免"高度算少了把字裁掉"。
  const lineHeight = { title: 56, meta: 34, step: 44, row: 34, conclusion: 36, foot: 26, gap: 20 }
  const measure = (item) => {
    ctx.font = `${item.kind === 'title' ? 'bold 44px' : item.kind === 'step' ? 'bold 30px' : '26px'} ${FONT}`
    const words = item.text.split('')
    const lines = []
    let cur = ''
    for (const ch of words) {
      const test = cur + ch
      if (ctx.measureText(test).width > bodyWidth - (item.kind === 'row' ? 40 : 0) && cur) {
        lines.push(cur)
        cur = ch
      } else {
        cur = test
      }
    }
    if (cur) lines.push(cur)
    return lines
  }

  let height = pad
  const layout = rows.map(item => {
    const lines = item.kind === 'gap' ? [] : measure(item)
    height += lines.length * lineHeight[item.kind] + (item.kind === 'gap' ? 8 : 10)
    return { item, lines }
  })
  height += pad

  canvas.width = width
  canvas.height = Math.max(600, height)

  ctx.fillStyle = COLOR.bg
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.strokeStyle = COLOR.line
  ctx.lineWidth = 2
  ctx.strokeRect(16, 16, canvas.width - 32, canvas.height - 32)

  let y = pad + 24
  for (const { item, lines } of layout) {
    if (item.kind === 'gap') {
      y += 8
      ctx.strokeStyle = COLOR.line
      ctx.beginPath()
      ctx.moveTo(pad, y)
      ctx.lineTo(width - pad, y)
      ctx.stroke()
      y += 14
      continue
    }
    const size = item.kind === 'title' ? 44 : item.kind === 'step' ? 30 : item.kind === 'foot' ? 22 : 26
    const weight = item.kind === 'title' || item.kind === 'step' ? 'bold' : 'normal'
    ctx.font = `${weight} ${size}px ${FONT}`
    ctx.fillStyle = item.kind === 'title' ? COLOR.text
      : item.kind === 'step' ? COLOR.accent
        : item.kind === 'meta' || item.kind === 'foot' ? COLOR.quiet
          : item.kind === 'conclusion' ? COLOR.watch : COLOR.text
    for (const line of lines) {
      ctx.fillText(line, pad + (item.kind === 'row' ? 24 : 0), y + size)
      y += lineHeight[item.kind]
    }
    if (item.kind === 'row' && item.extra) {
      ctx.font = `20px ${MONO}`
      ctx.fillStyle = COLOR.quiet
      ctx.fillText(String(item.extra), pad + 24, y + 14 < canvas.height - 24 ? y + 12 : y)
    }
    y += 10
  }
  return canvas
}

/** 触发下载。失败返回 false，由调用方决定提示什么。 */
export function downloadEvidencePng(ev, filename = 'evidence.png') {
  try {
    const canvas = drawEvidenceCard(ev)
    return new Promise(resolve => {
      canvas.toBlob(blob => {
        if (!blob) {
          resolve(false)
          return
        }
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => URL.revokeObjectURL(url), 1500)
        resolve(true)
      }, 'image/png')
    })
  } catch (_) {
    return Promise.resolve(false)
  }
}
