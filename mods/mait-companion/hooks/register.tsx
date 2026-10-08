import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type {
  AgentRun, BarStyle, BoundCard, Card, EventData, JiraRef, Palette, RateWindow, SessionData, WorkData,
} from '../types'

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
const NO_EVENTS: EventData = { agents: [] }
/** How often a running agent's elapsed time moves on screen. */
const TICK_MS = 5_000

const work = atom({ plugin: 'mait-companion', key: 'work' } as const, NO_WORK)
const session = atom({ plugin: 'mait-companion', key: 'session' } as const, {})
const palette = atom({ plugin: 'mait-companion', key: 'palette' } as const, null)
const style = atom({ plugin: 'mait-companion', key: 'style' } as const, 'blocks')
const events = atom({ plugin: 'mait-companion', key: 'events' } as const, NO_EVENTS)
const agentsOpen = atom({ plugin: 'mait-companion', key: 'agentsOpen' } as const, false)
const now = atom({ plugin: 'mait-companion', key: 'now' } as const, 0)

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

/**
 * claude-opus-5-5[1m] -> opus 5.5; anything else as the engine says it. The
 * window's size is the context segment's to show, beside what fills it.
 */
function shortModel(raw: string): string {
  const m = raw.match(/^claude-([a-z]+)-(\d+)(?:-(\d+))?(?:-\d{8})?(\[1m\])?$/i)
  if (!m) return raw
  const [, family, major, minor] = m
  return `${family!.toLowerCase()} ${major}${minor ? `.${minor}` : ''}`
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
  const git = cwd === undefined ? undefined : gitState(await run($, ['git', 'status', '--porcelain=v2', '--branch'], cwd))
  await update($, session, prev => ({
    ...prev,
    project: root?.split('/').filter(Boolean).at(-1),
    branch: branch || undefined,
    model: model ? shortModel(model) : undefined,
    modelId: model || undefined,
    dirty: git?.dirty,
    ahead: git?.ahead,
    behind: git?.behind,
  }))
}

/** `git status --porcelain=v2 --branch`: the changed paths, and ahead/behind when there is an upstream. */
function gitState(out: string | undefined): { dirty: number; ahead?: number; behind?: number } | undefined {
  if (out === undefined) return undefined
  const lines = out.split('\n').filter(Boolean)
  const ab = lines.find(l => l.startsWith('# branch.ab '))?.match(/\+(\d+) -(\d+)/)
  return {
    dirty: lines.filter(l => !l.startsWith('#')).length,
    ...(ab ? { ahead: Number(ab[1]), behind: Number(ab[2]) } : {}),
  }
}

type Usage = {
  context: { tokens?: number; percent?: number; window?: number }
  rateLimits: readonly { kind: string; percentUsed: number; resetsAt?: string }[]
}

async function applyUsage($: EngineInterface, u: Usage): Promise<void> {
  const { tokens, percent, window: size } = u.context
  // Without a clock reading the windows still draw, just with no reset times.
  const at = await quiet(() => $.clock.now())
  const window = (kind: string): RateWindow | undefined => {
    const r = u.rateLimits.find(l => l.kind === kind)
    if (!r) return undefined
    const resets = r.resetsAt === undefined || at === undefined ? NaN : Date.parse(r.resetsAt)
    return {
      percent: Math.round(r.percentUsed),
      ...(Number.isFinite(resets) && at !== undefined ? { resetsInMs: Math.max(0, resets - at) } : {}),
    }
  }
  await update($, session, prev => ({
    ...prev,
    ...(tokens !== undefined && percent !== undefined ? { context: { tokens, percent, window: size } } : {}),
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

// --- agents in flight -----------------------------------------------------------

// Kept from spawn to report: agent.spawn adds one, its loop's tool calls name
// what it is doing, its turn.complete removes it. $.agent.list() then drops any
// the engine has finished by other means (killed, failed) without a report,
// whether it still lists it as finished or has dropped it altogether.

const LIVE: ReadonlySet<string> = new Set(['pending', 'running', 'waiting'])

// A module variable, not state: a reload drops the old environment's timers
// with it, and session.start starts a fresh one if agents are still running.
let ticker: Timer | undefined

async function tick($: EngineInterface): Promise<void> {
  const t = await $.clock.now()
  await update($, now, () => t)
}

/** Tick `now` while any agent runs, so elapsed times move; stop when none does. */
async function syncTicker($: EngineInterface): Promise<void> {
  const running = (await read($, events)).agents.length > 0
  if (running && ticker === undefined) {
    // Claimed before the first await: agents spawned together each get here,
    // and only the first may start a timer.
    ticker = $.clock.every(TICK_MS, () => { void guarded(() => tick($)) })
    await tick($)
  } else if (!running && ticker !== undefined) {
    ticker.cancel()
    ticker = undefined
  }
}

async function setAgents($: EngineInterface, fn: (agents: readonly AgentRun[]) => readonly AgentRun[]): Promise<void> {
  await update($, events, prev => ({ ...prev, agents: fn(prev.agents) }))
  await syncTicker($)
}

async function reconcileAgents($: EngineInterface): Promise<void> {
  const listed = await quiet(() => $.agent.list())
  if (listed === undefined) return
  const live = new Set(listed.filter(a => LIVE.has(a.status)).map(a => a.id))
  // A workflow's agents are never listed, so only their report removes them.
  const keep = (a: AgentRun) => a.workflow === true || live.has(a.id)
  if (!(await read($, events)).agents.every(keep)) await setAgents($, agents => agents.filter(keep))
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
    await guarded(async () => { await reconcileAgents($); await syncTicker($) })
    return next(e)
  })

  on('command.run', { command: 'capture' }, async ($, e) => {
    const text = e.args.trim()
    if (!text) return { text: 'Usage: /capture <text>' }
    const out = await run($, ['mc-tool-inbox', 'add', '--', text])
    await guarded(() => refreshWork($))
    return { text: out === undefined ? 'Capture failed.' : out }
  })

  // Cards are bound, moved and completed by skills mid-turn. A subagent's turn
  // is its report: it leaves row 3, and the main turn refreshes the rest.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    const { agentId } = e
    if (agentId !== undefined) {
      await guarded(() => setAgents($, agents => agents.filter(a => a.id !== agentId)))
    } else {
      await guarded(() => Promise.all([refreshWork($), refreshWhere($), reconcileAgents($)]))
    }
    return result
  })

  // Teammates idle and wake rather than report once, so they are left out.
  on('agent.spawn', async ($, e, next) => {
    const result = await next(e)
    const agentId = 'agentId' in result ? result.agentId : undefined
    if (agentId !== undefined && !e.isTeammate) {
      await guarded(async () => {
        const startedAt = await $.clock.now()
        await setAgents($, agents => [
          ...agents.filter(a => a.id !== agentId),
          {
            id: agentId, type: e.subagentType, description: e.description, startedAt,
            ...(e.workflow ? { workflow: true as const } : {}),
          },
        ])
      })
    }
    return result
  })

  // What each agent is doing: the tool its loop last called. Not awaited, so
  // the call itself never waits on the bar.
  on('tool.call', ($, e, next) => {
    const { agentId, tool } = e
    if (agentId !== undefined) {
      void guarded(async () => {
        const { agents } = await read($, events)
        if (agents.some(a => a.id === agentId && a.lastTool !== tool)) {
          await setAgents($, all => all.map(a => (a.id === agentId ? { ...a, lastTool: tool } : a)))
        }
      })
    }
    return next(e)
  })

  // Raised whenever the context fill or a rate-limit window moves,
  // compactions included, so the usage segments need no polling.
  on('session.measure', async ($, e, next) => {
    await guarded(() => applyUsage($, e))
    return next(e)
  })

  // One blank row, then up to three full-width rows on the theme's panel
  // colour: the work (cards; Jira, in review, inbox), the session (project,
  // branch; model, context, rate limits), and the subagents running.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const c = await read($, palette)
    if (c === null) return next(e)
    const barStyle = await read($, style)
    const bg = c.panel
    const rows = [workSegments(await read($, work), c), sessionSegments(await read($, session), c)]
      .filter(r => r.length > 0)
    const { agents } = await read($, events)
    if (rows.length === 0 && agents.length === 0) return next(e)

    const draw = RENDERERS[barStyle]
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
          {ch.raw ? ch.text : ` ${ch.text} `}
        </Text>
      )
    }
    const row = (segments: Segment[], r: number) => {
      // In blocks, one cell of panel between badges keeps each one whole.
      const gap: Chunk[] = barStyle === 'blocks' ? [{ text: ' ', bg, fg: c.foreground, raw: true }] : []
      const side = (which: Segment['side']) =>
        segments.filter(s => s.side === which).flatMap((s, i) => [...(i > 0 ? gap : []), ...draw(s, c, bg)])
      return (
        <Box key={`row${r}`} width={e.props.bodyColumns} backgroundColor={bg} justifyContent="space-between">
          <Box flexShrink={1}>{side('left').map((ch, i) => chunk(ch, `l${i}`))}</Box>
          <Box flexShrink={0}>{side('right').map((ch, i) => chunk(ch, `r${i}`))}</Box>
        </Box>
      )
    }
    // Row 3 is drawn slim whatever the style: it changes too often for blocks.
    // Collapsed, one line of what the engine's own agent list can't say at a
    // glance: the mix of types and the longest-running time. Open, each agent's
    // task, current tool and time, grouped by type (no heading when all share one).
    const live = async () => {
      if (agents.length === 0) return []
      const isOpen = await read($, agentsOpen)
      const t = await read($, now)
      const width = e.props.bodyColumns
      const groups = byType(agents)
      const oldest = Math.min(...agents.map(a => a.startedAt))
      const header = (
        <Box key="agents" width={width} backgroundColor={bg}>
          <Text key="agents:glyph" backgroundColor={bg} color={c.accent} bold>{' ⋔ '}</Text>
          <Box key="agents:toggle-box" backgroundColor={bg} flexShrink={0}>
            <Button
              key="agents:toggle"
              plain
              label={`${isOpen ? '▾' : '▸'} ${agents.length} ${agents.length === 1 ? 'agent' : 'agents'}`}
              hover={{ underline: true }}
              onPress={() => { void guarded(() => update($, agentsOpen, v => !v)) }}
            />
          </Box>
          <Text key="agents:types" backgroundColor={bg} color={c.primary} wrap="truncate-end">
            {`  ${groups.map(([type, runs]) => (runs.length > 1 ? `${type} ×${runs.length}` : type)).join(' · ')}`}
          </Text>
          <Text key="agents:age" backgroundColor={bg} color={c.foreground} dimColor>
            {` · ${elapsed(t - oldest)} `}
          </Text>
        </Box>
      )
      if (!isOpen) return [header]
      const line = (a: AgentRun, last: boolean) => (
        <Box key={`agent:${a.id}`} width={width} backgroundColor={bg} justifyContent="space-between">
          <Box flexShrink={1}>
            <Text backgroundColor={bg} color={c.foreground} dimColor>{`   ${last ? '└' : '├'} `}</Text>
            <Text backgroundColor={bg} color={c.foreground} wrap="truncate-end">{a.description}</Text>
          </Box>
          <Box flexShrink={0}>
            {a.lastTool === undefined ? null : (
              <Text backgroundColor={bg} color={c.secondary}>{` ${toolLabel(a.lastTool)} `}</Text>
            )}
            <Text backgroundColor={bg} color={c.foreground} dimColor>{` ${elapsed(t - a.startedAt)} `}</Text>
          </Box>
        </Box>
      )
      return [header, ...groups.flatMap(([type, runs]) => [
        ...(groups.length > 1
          ? [(
            <Box key={`agents:group:${type}`} width={width} backgroundColor={bg}>
              <Text backgroundColor={bg} color={c.primary} bold>{`   ${type}`}</Text>
            </Box>
          )]
          : []),
        ...runs.map((a, i) => line(a, i === runs.length - 1)),
      ])]
    }
    return (
      <Box marginTop={1} flexDirection="column" width={e.props.bodyColumns}>
        {rows.map(row)}
        {await live()}
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
  /** Drawn as these coloured runs of text in every style, never on a block. */
  ink?: readonly Ink[]
  colour: string
}

/** A run of text in one colour; `fg` absent means the foreground. */
type Ink = { text: string; fg?: string; bold?: true; dim?: true }

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
    // Primary, as the cards whose tickets these are; apart from In Review's blue.
    segments.push({ side: 'right', glyph: '⌁', label: 'jira', links, colour: c.primary })
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
  if (d.branch) {
    segments.push({ side: 'left', glyph: '⎇', value: `${d.branch}${gitMarks(d)}`, quiet: true, colour: c.secondary })
  }
  if (d.model) segments.push(modelSegment(d.model, d.modelId, c))
  // Tokens over the window's size as the label, so the size reads as the context's.
  if (d.context) {
    const { tokens, percent, window: size } = d.context
    const used = size ? `${compact(tokens)}/${compact(size)}` : compact(tokens)
    segments.push({ side: 'right', glyph: used, label: used, value: `${gauge(percent)} ${percent}%`, colour: fill(percent, c) })
  }
  // Both windows in one segment, in the order the label names them, coloured by the fuller.
  const windows = ([['5h', d.fiveHour], ['7d', d.sevenDay]] as const).filter(
    (w): w is readonly ['5h' | '7d', RateWindow] => w[1] !== undefined)
  if (windows.length > 0) {
    const worst = windows.reduce((a, b) => (b[1].percent > a[1].percent ? b : a))[1]
    segments.push({
      side: 'right',
      glyph: '◷',
      label: windows.map(([name]) => name).join('·'),
      value: `${windows.map(([, w]) => w.percent).join('·')}%${resetMark(worst)}`,
      colour: fill(worst.percent, c),
    })
  }
  return segments
}

/** ` ±3 ↑1↓2`: changed paths, then commits ahead and behind; nothing when all are zero. */
function gitMarks(d: SessionData): string {
  const dirty = d.dirty ? ` ±${d.dirty}` : ''
  const ab = `${d.ahead ? `↑${d.ahead}` : ''}${d.behind ? `↓${d.behind}` : ''}`
  return `${dirty}${ab ? ` ${ab}` : ''}`
}

/** ` ↻41m` on a window at 80% or more, when the engine said when it resets. */
function resetMark(w: RateWindow): string {
  if (w.percent < 80 || w.resetsInMs === undefined) return ''
  const m = Math.ceil(w.resetsInMs / 60_000)
  return ` ↻${m < 60 ? `${m}m` : m < 48 * 60 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`}`
}

/**
 * The model in coloured text rather than a block, so the signals around it stand
 * out: `✦ opus` in accent, the version in foreground. A model id it can't read is
 * shown as the engine gave it, on a block.
 */
function modelSegment(name: string, id: string | undefined, c: Palette): Segment {
  const m = id?.match(/^claude-([a-z]+)-(\d+)(?:-(\d+))?(?:-\d{8})?(\[1m\])?$/i)
  if (!m) return { side: 'right', glyph: '✦', label: '✦', value: name, colour: c.accent }
  const [, family, major, minor] = m
  return {
    side: 'right',
    glyph: '✦',
    colour: c.accent,
    ink: [
      { text: '✦', fg: c.accent },
      { text: family!.toLowerCase(), fg: c.accent, bold: true },
      { text: `${major}${minor ? `.${minor}` : ''}`, bold: true },
    ],
  }
}

/** Eight cells, filled to the nearest eighth: ▰▰▰▱▱▱▱▱. */
function gauge(percent: number): string {
  const filled = Math.min(8, Math.max(0, Math.round(percent / 12.5)))
  return '▰'.repeat(filled) + '▱'.repeat(8 - filled)
}

/** Agents grouped by type, in the order each type first started. */
function byType(agents: readonly AgentRun[]): [string, AgentRun[]][] {
  const groups = new Map<string, AgentRun[]>()
  for (const a of agents) groups.set(a.type, [...(groups.get(a.type) ?? []), a])
  return [...groups]
}

/** An agent's last tool as the row names it; the hand-back reads as what it is. */
function toolLabel(tool: string): string {
  return tool === 'SubagentHandback' ? 'reporting' : tool
}

/** 8_000 -> 8s, 72_000 -> 1m12s, 3_780_000 -> 1h03m; never negative. */
function elapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}m`
}

/** 1234 -> 1.2k, 142000 -> 142k, 1000000 -> 1M. */
function compact(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${+(n / 1000).toFixed(1)}k`
  return String(n)
}

// --- renderers: how the bar says it --------------------------------------------

/** `raw` text is drawn as given; any other is padded with a space either side. */
type Chunk = { text: string; bg?: string; fg: string; bold?: boolean; dim?: boolean; href?: string; raw?: true }

/** A key with no link is drawn as plain text on the same background. */
function linkChunks(s: Segment, bg: string | undefined, c: Palette): Chunk[] {
  return (s.links ?? []).map(l => ({ text: l.key, bg, fg: c.foreground, href: l.href ?? undefined }))
}

// No blocks: a coloured glyph and value, the detail in plain foreground.
const slim = (s: Segment, c: Palette, bg: string | undefined): Chunk[] => s.ink ? inkChunks(s.ink, c, bg) : [
  { text: s.value === undefined ? s.glyph : `${s.glyph} ${s.value}`, bg, fg: s.colour, bold: true },
  ...(s.detail ? [{ text: s.detail, bg, fg: c.foreground }] : []),
  ...linkChunks(s, bg, c),
]

/** Ink runs joined by single spaces, one chunk each so each keeps its colour. */
function inkChunks(ink: readonly Ink[], c: Palette, bg: string | undefined): Chunk[] {
  return ink.map((r, i) => ({
    text: `${i === 0 ? ' ' : ''}${r.text} `,
    bg, fg: r.fg ?? c.foreground, bold: r.bold, dim: r.dim, raw: true,
  }))
}

const RENDERERS: Record<BarStyle, (s: Segment, c: Palette, bg: string | undefined) => Chunk[]> = {
  // A badge: the label on surface joined to its value on the segment's colour,
  // so each label reads with its own value. With no value the label takes the colour.
  blocks: (s, c, bg) => s.ink ? inkChunks(s.ink, c, bg) : s.quiet ? slim(s, c, bg) : [
    ...(s.label
      ? [s.value === undefined
        ? { text: s.label, bg: s.colour, fg: c.background, bold: true }
        : { text: s.label, bg: c.surface, fg: c.foreground }]
      : []),
    ...(s.value !== undefined ? [{ text: s.value, bg: s.colour, fg: c.background, bold: true }] : []),
    ...(s.detail ? [{ text: s.detail, bg: c.surface, fg: c.foreground, bold: true }] : []),
    ...linkChunks(s, c.surface, c),
  ],
  slim,
}
