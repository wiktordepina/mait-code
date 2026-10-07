import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { BarStyle, BoundCard, Card, JiraRef, Palette, SessionData, WorkData } from '../types'

// A thin client of the mc-tool-* and mait-code CLIs: every capability and
// every colour lives in mait-code; this mod only calls them and draws. It rides
// an early-access API, so it fails closed: a missing CLI, output it can't read
// or a host call that throws leaves its segment out, never the session broken.

const ROLES = [
  'primary', 'secondary', 'accent', 'foreground', 'background',
  'surface', 'panel', 'success', 'warning', 'error',
] as const
const STYLES: readonly BarStyle[] = ['blocks', 'slim']
const NO_WORK: WorkData = { bound: [], inReview: [], inbox: 0 }

const work = atom({ plugin: 'mait-companion', key: 'work' } as const, NO_WORK)
const session = atom({ plugin: 'mait-companion', key: 'session' } as const, {})
const palette = atom({ plugin: 'mait-companion', key: 'palette' } as const, null)
const style = atom({ plugin: 'mait-companion', key: 'style' } as const, 'blocks')

// --- reading ------------------------------------------------------------------

/** Run a command; its trimmed stdout, or undefined on any failure. */
async function run($: EngineInterface, argv: string[], cwd?: string): Promise<string | undefined> {
  try {
    const { exitCode, stdout } = await $.process.run(argv, { timeoutMs: 10_000, cwd })
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

async function quiet<T>(call: () => Promise<T>): Promise<T | undefined> {
  try {
    return await call()
  } catch {
    return undefined
  }
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

/** Jira links as the board resolved them; one it can't read is dropped. */
function jira(v: unknown): JiraRef[] {
  if (!Array.isArray(v)) return []
  return v.flatMap(j => {
    if (!isRecord(j) || typeof j.key !== 'string') return []
    return [{ key: j.key, href: typeof j.url === 'string' && j.url.startsWith('https://') ? j.url : null }]
  })
}

function boundCards(v: unknown): BoundCard[] | undefined {
  const base = cards(v)
  if (base === undefined || !Array.isArray(v)) return undefined
  return base.map((c, i) => ({ ...c, jira: jira((v[i] as Record<string, unknown>).jira) }))
}

// One aggregate call per refresh. Anything unreadable empties the card
// segments rather than showing stale ones.
async function refreshWork($: EngineInterface): Promise<void> {
  const id = await quiet(() => $.session.id())
  const out = id === undefined
    ? undefined
    : await runJson($, ['mc-tool-board', 'summary', '--json', '--session', id])
  const bound = isRecord(out) ? boundCards(out.bound) : undefined
  const inReview = isRecord(out) ? cards(out.in_review) : undefined
  const inbox = isRecord(out) && typeof out.inbox === 'number' ? out.inbox : undefined
  await update($, work, () => (bound && inReview && inbox !== undefined ? { bound, inReview, inbox } : NO_WORK))
}

/** claude-opus-5-5[1m] -> opus 5.5 · 1M; anything else as the engine says it. */
function shortModel(raw: string): string {
  const m = raw.match(/^claude-([a-z]+)-(\d+)(?:-(\d+))?(?:-\d{8})?(\[1m\])?$/i)
  if (!m) return raw
  const [, family, major, minor, wide] = m
  return `${family!.toLowerCase()} ${major}${minor ? `.${minor}` : ''}${wide ? ' · 1M' : ''}`
}

// Where the session is: read after each turn, as /cd, a checkout or /model
// may have moved it.
async function refreshWhere($: EngineInterface): Promise<void> {
  const [root, cwd, model] = await Promise.all([
    quiet(() => $.session.root()),
    quiet(() => $.session.cwd()),
    quiet(() => $.session.model()),
  ])
  const branch = cwd === undefined
    ? undefined
    : (await run($, ['git', 'symbolic-ref', '--short', '-q', 'HEAD'], cwd))
      ?? (await run($, ['git', 'rev-parse', '--short', 'HEAD'], cwd))
  await update($, session, prev => ({
    ...prev,
    project: root?.split('/').filter(Boolean).at(-1),
    branch: branch || undefined,
    model: model ? shortModel(model) : undefined,
  }))
}

type Usage = {
  context: { tokens?: number; percent?: number }
  rateLimits: readonly { kind: string; percentUsed: number }[]
}

async function applyUsage($: EngineInterface, u: Usage): Promise<void> {
  const { tokens, percent } = u.context
  const window = (kind: string) => {
    const r = u.rateLimits.find(l => l.kind === kind)
    return r ? { percent: Math.round(r.percentUsed) } : undefined
  }
  await update($, session, prev => ({
    ...prev,
    ...(tokens !== undefined && percent !== undefined ? { context: { tokens, percent } } : {}),
    fiveHour: window('five_hour'),
    sevenDay: window('seven_day'),
  }))
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

async function guarded(task: () => Promise<unknown>): Promise<void> {
  try {
    await task()
  } catch {
    // A failed refresh leaves the bar as it was; the session carries on.
  }
}

/** Open a link in the browser: xdg-open on Linux, open on macOS. */
async function openLink($: EngineInterface, href: string): Promise<void> {
  if ((await run($, ['xdg-open', href])) === undefined) await run($, ['open', href])
}

// --- hooks --------------------------------------------------------------------

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Isolated: a refused registration must not cost the bar its refresh.
    await guarded(() => $.command.register({
      name: 'capture',
      description: 'Capture a thought to the mait-code inbox without a model turn.',
    }))
    await guarded(() => Promise.all([
      refreshSettings($),
      refreshWork($),
      refreshWhere($),
      $.session.usage().then(u => applyUsage($, u)),
    ]))
    return next(e)
  })

  on('command.run', { command: 'capture' }, async ($, e) => {
    const text = e.args.trim()
    if (!text) return { text: 'Usage: /capture <text>' }
    const out = await run($, ['mc-tool-inbox', 'add', '--', text])
    await guarded(() => refreshWork($))
    return { text: out === undefined ? 'Capture failed.' : out }
  })

  // Cards are bound, moved and completed by skills mid-turn.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await guarded(() => Promise.all([refreshWork($), refreshWhere($)]))
    return result
  })

  // Raised whenever the context fill or a rate-limit window moves,
  // compactions included, so the usage segments need no polling.
  on('session.measure', async ($, e, next) => {
    await guarded(() => applyUsage($, e))
    return next(e)
  })

  // One blank row, then two full-width rows on the theme's panel colour: the
  // work above (cards; Jira, in review, inbox), the session below (project,
  // branch; model, context, rate limits).
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const c = await read($, palette)
    if (c === null) return next(e)
    const rows = [workSegments(await read($, work), c), sessionSegments(await read($, session), c)]
      .filter(r => r.length > 0)
    if (rows.length === 0) return next(e)

    const draw = RENDERERS[await read($, style)]
    const { Box, Text, Button } = $.ui.resolve(e)
    // A linked Jira key is a plain Button that opens the browser itself: a
    // Link prints its URL beside the text wherever the engine doubts the
    // terminal does OSC 8 (under a multiplexer, say).
    const chunk = (ch: Chunk, key: string) => {
      const href = ch.href
      if (href) {
        return (
          <Box key={key} backgroundColor={ch.bg} paddingX={1}>
            <Button
              key={`jira:${ch.text}`}
              plain
              label={ch.text}
              hover={{ underline: true }}
              onPress={() => { void openLink($, href) }}
            />
          </Box>
        )
      }
      return (
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
    }
    const row = (segments: Segment[], r: number) => {
      const side = (which: Segment['side']) =>
        segments.filter(s => s.side === which).flatMap(s => draw(s, c))
      return (
        <Box key={`row${r}`} width={e.props.bodyColumns} backgroundColor={c.panel} justifyContent="space-between">
          <Box flexShrink={1}>{side('left').map((ch, i) => chunk(ch, `l${i}`))}</Box>
          <Box flexShrink={0}>{side('right').map((ch, i) => chunk(ch, `r${i}`))}</Box>
        </Box>
      )
    }
    return (
      <Box marginTop={1} flexDirection="column" width={e.props.bodyColumns}>
        {rows.map(row)}
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
  /** Absent on a segment that is all links. */
  value?: string
  detail?: string
  links?: readonly JiraRef[]
  /** Drawn slim even in the blocks style: ambient facts, not signals. */
  quiet?: true
  colour: string
}

function fill(percent: number, c: Palette): string {
  return percent < 50 ? c.success : percent < 80 ? c.warning : c.error
}

function workSegments(d: WorkData, c: Palette): Segment[] {
  const segments: Segment[] = d.bound.map(card => ({
    side: 'left',
    glyph: '◆',
    value: `#${card.id}`,
    detail: card.title,
    colour: c.primary,
  }))
  // Every bound card's keys in one block, first on the right, apart from titles.
  const seen = new Set<string>()
  const links = d.bound.flatMap(card => card.jira).filter(l => !seen.has(l.key) && seen.add(l.key))
  if (links.length > 0) {
    segments.push({ side: 'right', glyph: '⌁', label: 'jira', links, colour: c.secondary })
  }
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
    segments.push({ side: 'right', glyph: '✉', label: 'inbox', value: String(d.inbox), colour: c.accent })
  }
  return segments
}

// Row 2 reads left to right as "where" then "what it's using".
function sessionSegments(d: SessionData, c: Palette): Segment[] {
  const segments: Segment[] = []
  if (d.project) segments.push({ side: 'left', glyph: '▣', value: d.project, quiet: true, colour: c.primary })
  if (d.branch) segments.push({ side: 'left', glyph: '⎇', value: d.branch, quiet: true, colour: c.secondary })
  if (d.model) segments.push({ side: 'right', glyph: '✦', label: '✦', value: d.model, colour: c.accent })
  if (d.context) {
    const { tokens, percent } = d.context
    segments.push({
      side: 'right',
      glyph: pie(percent),
      label: pie(percent),
      value: `${compact(tokens)} · ${percent}%`,
      colour: fill(percent, c),
    })
  }
  for (const [label, w] of [['5h', d.fiveHour], ['7d', d.sevenDay]] as const) {
    if (w) segments.push({ side: 'right', glyph: '◷', label, value: `${w.percent}%`, colour: fill(w.percent, c) })
  }
  return segments
}

/** The context glyph fills as the window does: ○ ◔ ◑ ◕ ●. */
function pie(percent: number): string {
  return '○◔◑◕●'[Math.min(4, Math.max(0, Math.round(percent / 25)))]!
}

/** 1234 -> 1.2k, 142000 -> 142k, 1000000 -> 1M. */
function compact(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${+(n / 1000).toFixed(1)}k`
  return String(n)
}

// --- renderers: how the bar says it --------------------------------------------

type Chunk = { text: string; bg: string; fg: string; bold?: boolean; dim?: boolean; href?: string }

/** A key with no link is drawn as plain text on the same background. */
function linkChunks(s: Segment, bg: string, c: Palette): Chunk[] {
  return (s.links ?? []).map(l => ({ text: l.key, bg, fg: c.foreground, href: l.href ?? undefined }))
}

// No blocks: a coloured glyph and value, the detail in plain foreground.
const slim = (s: Segment, c: Palette): Chunk[] => [
  { text: s.value === undefined ? s.glyph : `${s.glyph} ${s.value}`, bg: c.panel, fg: s.colour, bold: true },
  ...(s.detail ? [{ text: s.detail, bg: c.panel, fg: c.foreground }] : []),
  ...linkChunks(s, c.panel, c),
]

const RENDERERS: Record<BarStyle, (s: Segment, c: Palette) => Chunk[]> = {
  // Dim label on the panel, value on the segment's colour, detail and links on surface.
  blocks: (s, c) => s.quiet ? slim(s, c) : [
    ...(s.label ? [{ text: s.label, bg: c.panel, fg: c.foreground, dim: true }] : []),
    ...(s.value !== undefined ? [{ text: s.value, bg: s.colour, fg: c.background, bold: true }] : []),
    ...(s.detail ? [{ text: s.detail, bg: c.surface, fg: c.foreground, bold: true }] : []),
    ...linkChunks(s, c.surface, c),
  ],
  slim,
}
