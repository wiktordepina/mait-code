import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { BarData, BarStyle, Card, Palette } from '../types'

// A read-only consumer of the mc-tool-* and mait-code CLIs: every capability
// and every colour lives in mait-code; this mod only calls and draws. It rides
// an early-access API, so it fails closed: a missing CLI, output it can't read
// or a host call that throws leaves the bar empty, never the session broken.

const ROLES = [
  'primary', 'secondary', 'accent', 'foreground', 'background',
  'surface', 'panel', 'success', 'warning', 'error',
] as const
const STYLES: readonly BarStyle[] = ['blocks', 'slim']
const EMPTY: BarData = { bound: [], inReview: [], inbox: 0 }

const data = atom({ plugin: 'mait-companion', key: 'data' } as const, EMPTY)
const palette = atom({ plugin: 'mait-companion', key: 'palette' } as const, null)
const style = atom({ plugin: 'mait-companion', key: 'style' } as const, 'blocks')

/** Run a CLI; its trimmed stdout, or undefined on any failure. */
async function run($: EngineInterface, argv: string[]): Promise<string | undefined> {
  try {
    const { exitCode, stdout } = await $.process.run(argv, { timeoutMs: 10_000 })
    return exitCode === 0 ? stdout.trim() : undefined
  } catch {
    return undefined
  }
}

async function runJson($: EngineInterface, argv: string[]): Promise<unknown> {
  const raw = await run($, argv)
  try {
    return raw === undefined ? undefined : JSON.parse(raw)
  } catch {
    return undefined
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function cards(v: unknown): Card[] | undefined {
  if (!Array.isArray(v)) return undefined
  const out: Card[] = []
  for (const c of v) {
    if (!isRecord(c) || typeof c.id !== 'number' || typeof c.title !== 'string') return undefined
    out.push({ id: c.id, title: c.title })
  }
  return out
}

// One aggregate call per refresh. Anything unreadable empties the card
// segments rather than showing stale ones; context comes from the engine.
async function refreshData($: EngineInterface): Promise<void> {
  let session: string | undefined
  try {
    session = await $.session.id()
  } catch {
    session = undefined
  }
  const out = session === undefined
    ? undefined
    : await runJson($, ['mc-tool-board', 'summary', '--json', '--session', session])
  const bound = isRecord(out) ? cards(out.bound) : undefined
  const inReview = isRecord(out) ? cards(out.in_review) : undefined
  const inbox = isRecord(out) && typeof out.inbox === 'number' ? out.inbox : undefined
  const fresh = bound && inReview && inbox !== undefined ? { bound, inReview, inbox } : EMPTY
  await update($, data, prev => ({ ...prev, ...fresh }))
}

async function refreshContext($: EngineInterface): Promise<void> {
  try {
    const { context } = await $.session.usage()
    if (context.tokens === undefined || context.percent === undefined) return
    const fill = { tokens: context.tokens, percent: context.percent }
    await update($, data, prev => ({ ...prev, context: fill }))
  } catch {
    // Usage unavailable: the segment keeps its last value, or stays absent.
  }
}

// Theme and style are read once per session start, resolved by mait-code
// itself (env -> settings.toml -> default, unknown themes -> mait-dark).
async function refreshSettings($: EngineInterface): Promise<void> {
  const [themed, styled] = await Promise.all([
    runJson($, ['mait-code', 'settings', 'get', 'theme', '--palette']),
    runJson($, ['mait-code', 'settings', 'get', 'status-bar-style', '--json']),
  ])
  const colours = isRecord(themed) ? themed.palette : undefined
  const valid = isRecord(colours)
    && ROLES.every(r => typeof colours[r] === 'string' && /^#[0-9a-f]{6}$/i.test(colours[r] as string))
  await update($, palette, () => (valid ? (colours as Palette) : null))
  const name = isRecord(styled) ? styled.value : undefined
  await update($, style, () => ((STYLES as readonly unknown[]).includes(name) ? (name as BarStyle) : 'blocks'))
}

async function guarded(work: () => Promise<unknown>): Promise<void> {
  try {
    await work()
  } catch {
    // A failed refresh leaves the bar as it was; the session carries on.
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Isolated: a refused registration must not cost the bar its refresh.
    await guarded(() => $.command.register({
      name: 'capture',
      description: 'Capture a thought to the mait-code inbox without a model turn.',
    }))
    await guarded(() => Promise.all([refreshSettings($), refreshData($), refreshContext($)]))
    return next(e)
  })

  on('command.run', { command: 'capture' }, async ($, e) => {
    const text = e.args.trim()
    if (!text) return { text: 'Usage: /capture <text>' }
    const out = await run($, ['mc-tool-inbox', 'add', '--', text])
    await guarded(() => refreshData($))
    return { text: out === undefined ? 'Capture failed.' : out }
  })

  // Cards are bound, moved and completed by skills mid-turn.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await guarded(() => Promise.all([refreshData($), refreshContext($)]))
    return result
  })

  // A compaction empties most of the window; show it straight away.
  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    await guarded(() => refreshContext($))
    return result
  })

  // One blank row, then a full-width bar on the theme's panel colour: work in
  // hand on the left, things waiting on you on the right.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const c = await read($, palette)
    if (c === null) return next(e)
    const segments = buildSegments(await read($, data), c)
    if (segments.length === 0) return next(e)

    const draw = RENDERERS[await read($, style)]
    const left = segments.filter(s => s.side === 'left').flatMap(s => draw(s, c))
    const right = segments.filter(s => s.side === 'right').flatMap(s => draw(s, c))
    const { Box, Text } = $.ui.resolve(e)
    const chunk = (ch: Chunk, key: string) => (
      <Text
        key={key}
        backgroundColor={ch.bg}
        color={ch.fg}
        bold={ch.bold}
        dimColor={ch.dim}
        wrap="truncate-end"
      >
        {` ${ch.text} `}
      </Text>
    )
    return (
      <Box
        marginTop={1}
        width={e.props.bodyColumns}
        backgroundColor={c.panel}
        justifyContent="space-between"
      >
        <Box flexShrink={1}>{left.map((ch, i) => chunk(ch, `l${i}`))}</Box>
        <Box flexShrink={0}>{right.map((ch, i) => chunk(ch, `r${i}`))}</Box>
      </Box>
    )
  })
}

// --- segments: what the bar says ---------------------------------------------

type Segment = {
  side: 'left' | 'right'
  glyph: string
  /** Shown before the value in the blocks style; omitted where the value speaks for itself. */
  label?: string
  value: string
  detail?: string
  colour: string
}

function buildSegments(d: BarData, c: Palette): Segment[] {
  const segments: Segment[] = d.bound.map(card => ({
    side: 'left',
    glyph: '◆',
    value: `#${card.id}`,
    detail: card.title,
    colour: c.primary,
  }))
  const [first] = d.inReview
  if (first) {
    segments.push({
      side: 'right',
      glyph: '⟳',
      label: 'in review',
      value: d.inReview.length === 1 ? `#${first.id}` : String(d.inReview.length),
      colour: c.secondary,
    })
  }
  if (d.inbox > 0) {
    segments.push({
      side: 'right',
      glyph: '✉',
      label: 'inbox',
      value: String(d.inbox),
      colour: c.accent,
    })
  }
  if (d.context) {
    const { tokens, percent } = d.context
    segments.push({
      side: 'right',
      glyph: '◔',
      label: 'context',
      value: `${compact(tokens)} · ${percent}%`,
      colour: percent < 50 ? c.success : percent < 80 ? c.warning : c.error,
    })
  }
  return segments
}

/** 1234 -> 1.2k, 142000 -> 142k, 1000000 -> 1M. */
function compact(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${+(n / 1000).toFixed(1)}k`
  return String(n)
}

// --- renderers: how the bar says it --------------------------------------------

type Chunk = { text: string; bg: string; fg: string; bold?: boolean; dim?: boolean }

const RENDERERS: Record<BarStyle, (s: Segment, c: Palette) => Chunk[]> = {
  // Dim label on the panel, value on the segment's colour, detail on surface.
  blocks: (s, c) => [
    ...(s.label ? [{ text: s.label, bg: c.panel, fg: c.foreground, dim: true }] : []),
    { text: s.value, bg: s.colour, fg: c.background, bold: true },
    ...(s.detail ? [{ text: s.detail, bg: c.surface, fg: c.foreground, bold: true }] : []),
  ],
  // No blocks: a coloured glyph and value, the detail in plain foreground.
  slim: (s, c) => [
    { text: `${s.glyph} ${s.value}`, bg: c.panel, fg: s.colour, bold: true },
    ...(s.detail ? [{ text: s.detail, bg: c.panel, fg: c.foreground }] : []),
  ],
}
