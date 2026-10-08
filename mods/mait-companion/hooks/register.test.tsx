import { test, expect, mock } from 'claude-code/testing'
import type { On } from 'claude-code'

const SURFACES = ['terminal', 'desktop'] as const

const PALETTE = {
  primary: '#4FB6C7', secondary: '#7AA2F7', accent: '#C792EA', foreground: '#D7DAE0',
  background: '#0F1218', surface: '#161B25', panel: '#1D2230',
  success: '#87D96C', warning: '#F9C560', error: '#EF6B6B',
}

const BAR = {
  plugin: 'mait-companion',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 9 },
    view: {},
  },
} as const

type Summary = { bound?: unknown; in_review?: unknown; inbox?: unknown }

type World = {
  summary?: Summary | string
  palette?: unknown
  style?: string
  canRegister?: boolean
  /** argv[0]s that fail as if not installed. */
  missing?: string[]
  context?: { tokens: number; percent: number }
  session?: string
  /** The engine's own session nouns throw, as under API drift. */
  hostThrows?: boolean
  root?: string
  model?: string
  rateLimits?: { kind: string; percentUsed: number; resetsAt?: string }[]
  /** The branch checked out; null for a detached HEAD at `abc1234`. */
  branch?: string | null
  /** What `git status --porcelain=v2 --branch` prints. */
  gitStatus?: string
}

/**
 * The engine beneath the plugin: its own (empty) band, and the mait-code CLIs.
 * Registered once per test (before the first `$` call); `world` is read live,
 * so a test changes it between session starts to try several cases.
 */
function engine(on: On, world: World = {}): string[][] {
  const calls: string[][] = []
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.id', () => {
    if (world.hostThrows) throw new Error('gone')
    return { value: world.session ?? 'sess-1' }
  })
  on('session.usage', () => {
    if (world.hostThrows) throw new Error('gone')
    return {
    value: {
      startedAt: 0,
      context: world.context
        ? { ...world.context, window: 1_000_000 }
        : { tokens: undefined, window: 1_000_000, percent: undefined },
      rateLimits: world.rateLimits ?? [],
    },
  }
  })
  for (const noun of ['root', 'cwd'] as const) {
    on(`session.${noun}`, () => {
      if (world.hostThrows || world.root === undefined) throw new Error('gone')
      return { value: world.root }
    })
  }
  on('session.model', () => {
    if (world.hostThrows || world.model === undefined) throw new Error('gone')
    return { value: world.model }
  })
  on('command.register', ($, e) =>
    world.canRegister === false ? { deny: 'API drift' } : { value: { command: e.name } },
  )
  on('process.run', ($, e) => {
    calls.push([...e.argv])
    const [bin] = e.argv
    if (bin && world.missing?.includes(bin)) throw new Error(`${bin}: not found`)
    let stdout = ''
    const summary = world.summary ?? { bound: [], in_review: [], inbox: 0 }
    if (bin === 'mc-tool-board') {
      stdout = typeof summary === 'string' ? summary : JSON.stringify({ project: 'p', counts: {}, ...summary })
    } else if (bin === 'mc-tool-inbox') {
      stdout = `Captured #9: ${e.argv.at(-1)}`
    } else if (bin === 'git' && e.argv[1] === 'symbolic-ref') {
      if (world.branch === null) return { value: { exitCode: 1, stdout: '', stderr: '' } }
      stdout = world.branch ?? ''
    } else if (bin === 'git' && e.argv[1] === 'status') {
      stdout = world.gitStatus ?? ''
    } else if (bin === 'git' && e.argv[1] === 'rev-parse') {
      stdout = 'abc1234'
    } else if (e.argv.includes('--palette')) {
      stdout = JSON.stringify({ theme: 'x', resolved: 'x', palette: world.palette ?? PALETTE })
    } else if (e.argv.includes('status-bar-style')) {
      stdout = JSON.stringify({ key: 'status-bar-style', value: world.style ?? 'blocks', source: 'file' })
    }
    return { value: { exitCode: 0, stdout, stderr: '' } }
  })
  return calls
}

async function start($: Parameters<Parameters<typeof test>[1]>[0]) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
}

const card = (id: number, title = `Card ${id}`) => ({ id, title })

// --- /capture -------------------------------------------------------------------

test('capture with no text answers usage', async ($, on) => {
  engine(on)
  await start($)
  const { text } = await $.command.run({ command: 'capture', args: '   ' })
  expect(text).toBe('Usage: /capture <text>')
})

test('capture files to the inbox, text after --, and refreshes the bar', async ($, on) => {
  const calls = engine(on)
  await start($)
  const before = calls.length
  const { text } = await $.command.run({ command: 'capture', args: ' -v looks odd ' })
  expect(text).toBe('Captured #9: -v looks odd')
  expect(calls[before]).toEqual(['mc-tool-inbox', 'add', '--', '-v looks odd'])
  expect(calls.slice(before + 1).some(argv => argv[0] === 'mc-tool-board')).toBe(true)
})

test('capture says so when the inbox CLI is missing', async ($, on) => {
  engine(on, { missing: ['mc-tool-inbox'] })
  await start($)
  const { text } = await $.command.run({ command: 'capture', args: 'a thought' })
  expect(text).toBe('Capture failed.')
})

test('the bar still draws when /capture cannot register', async ($, on) => {
  engine(on, { canRegister: false, summary: { bound: [card(7)], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /#7/ })).toBeDefined()
  await ui.unmount()
})

// --- segments -----------------------------------------------------------------

test('bound cards show #id on primary and title on surface, with no label', async ($, on) => {
  engine(on, { summary: { bound: [card(42, 'Ship the band')], in_review: [], inbox: 0 } })
  await start($)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...BAR, surface })
    const id = await ui.find({ type: 'Text', text: /#42/ })
    const title = await ui.find({ type: 'Text', text: /Ship the band/ })
    expect(id?.props.backgroundColor).toBe(PALETTE.primary)
    expect(title?.props.backgroundColor).toBe(PALETTE.surface)
    expect(await ui.find({ type: 'Text', text: /working on/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('the summary is asked for this session', async ($, on) => {
  const calls = engine(on, { session: 'abc-123' })
  await start($)
  expect(calls).toContainEqual(['mc-tool-board', 'summary', '--json', '--session', 'abc-123'])
})

test('one card in review shows its #id', async ($, on) => {
  engine(on, { summary: { bound: [], in_review: [card(158)], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /in review/ })).toBeDefined()
  const value = await ui.find({ type: 'Text', text: /#158/ })
  expect(value?.props.backgroundColor).toBe(PALETTE.secondary)
  await ui.unmount()
})

test('several cards in review show the count', async ($, on) => {
  engine(on, { summary: { bound: [], in_review: [card(1), card(2), card(3)], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ 3 $/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /#1/ })).toBeUndefined()
  await ui.unmount()
})

test('the inbox shows its count on accent, and hides at zero', async ($, on) => {
  engine(on, { summary: { bound: [card(1)], in_review: [], inbox: 4 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^ 4 $/ }))?.props.backgroundColor).toBe(PALETTE.accent)
  await ui.unmount()
})

test('context fill is coloured by how full the window is', async ($, on) => {
  const cases = [
    { tokens: 120_000, percent: 12, colour: PALETTE.success, text: /^ ▰▱▱▱▱▱▱▱ 12% $/ },
    { tokens: 612_000, percent: 61, colour: PALETTE.warning, text: /^ ▰▰▰▰▰▱▱▱ 61% $/ },
    { tokens: 1_000_000, percent: 80, colour: PALETTE.error, text: /^ ▰▰▰▰▰▰▱▱ 80% $/ },
  ]
  const world: World = {}
  engine(on, world)
  for (const c of cases) {
    world.context = c
    await start($)
    const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
    expect((await ui.find({ type: 'Text', text: c.text }))?.props.backgroundColor).toBe(c.colour)
    await ui.unmount()
  }
})

test('the bar is hidden entirely when it has no segments', async ($, on) => {
  engine(on)
  await start($)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...BAR, surface })
    expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
    await ui.unmount()
  }
})

test('the bar yields to a survey', async ($, on) => {
  engine(on, { summary: { bound: [card(5)], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, props: { ...BAR.props, hasSurvey: true }, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /#5/ })).toBeUndefined()
  await ui.unmount()
})

// --- styles and theme ---------------------------------------------------------

test('both styles draw on both surfaces', async ($, on) => {
  const world: World = { summary: { bound: [card(161)], in_review: [card(9)], inbox: 2 } }
  engine(on, world)
  for (const style of ['blocks', 'slim']) {
    world.style = style
    await start($)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ ...BAR, surface })
      expect(await ui.find({ type: 'Text', text: /#161/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /#9/ })).toBeDefined()
      await ui.unmount()
    }
  }
})

test('slim draws glyphs on the panel instead of blocks', async ($, on) => {
  engine(on, { style: 'slim', summary: { bound: [card(3)], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  const value = await ui.find({ type: 'Text', text: /◆ #3/ })
  expect(value?.props.backgroundColor).toBe(PALETTE.panel)
  expect(value?.props.color).toBe(PALETTE.primary)
  await ui.unmount()
})

test('an unknown style falls back to blocks', async ($, on) => {
  engine(on, { style: 'powerline', summary: { bound: [card(3)], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /#3/ }))?.props.backgroundColor).toBe(PALETTE.primary)
  await ui.unmount()
})

test('colours come from the mait-code palette', async ($, on) => {
  const pink = { ...PALETTE, primary: '#FF6AC1' }
  engine(on, { palette: pink, summary: { bound: [card(1)], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /#1/ }))?.props.backgroundColor).toBe('#FF6AC1')
  await ui.unmount()
})

// --- failing closed -------------------------------------------------------------

test('a palette it cannot read draws nothing', async ($, on) => {
  const world: World = { summary: { bound: [card(1)], in_review: [], inbox: 0 } }
  engine(on, world)
  for (const palette of [{ ...PALETTE, panel: 'ansi_default' }, { primary: '#000000' }, 'nope']) {
    world.palette = palette
    await start($)
    const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
    expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
    await ui.unmount()
  }
})

test('a missing mait-code CLI draws nothing', async ($, on) => {
  engine(on, { missing: ['mait-code'], summary: { bound: [card(1)], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
  await ui.unmount()
})

test('a missing or garbled board summary draws no card segments', async ($, on) => {
  const cases: World[] = [
    { missing: ['mc-tool-board'] },
    { summary: 'not json' },
    { summary: { bound: [{ id: '1', title: 'x' }], in_review: [], inbox: 0 } },
    { summary: { bound: [card(1)], in_review: [] } },
  ]
  const world: World = {}
  engine(on, world)
  for (const c of cases) {
    Object.assign(world, { missing: undefined, summary: undefined }, c)
    await start($)
    const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
    expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
    await ui.unmount()
  }
})

test('the session still starts when every host call throws', async ($, on) => {
  engine(on, {
    canRegister: false,
    hostThrows: true,
    missing: ['mait-code', 'mc-tool-board', 'mc-tool-inbox'],
  })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
  await ui.unmount()
})

test('a turn refreshes the bar', async ($, on) => {
  const world: World = { summary: { bound: [], in_review: [], inbox: 0 } }
  engine(on, world)
  on('turn.complete', () => ({ text: 'done' }))
  await start($)
  world.summary = { bound: [card(12, 'Picked up mid-turn')], in_review: [], inbox: 0 }
  await $.turn.complete({
    answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer',
  })
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /#12/ })).toBeDefined()
  await ui.unmount()
})

// --- row 2: the session ----------------------------------------------------------

const WHERE: World = {
  root: '/home/me/projects/mait-code',
  model: 'claude-opus-5-5[1m]',
  branch: 'feat/two-rows',
  context: { tokens: 142_000, percent: 14 },
  rateLimits: [
    { kind: 'five_hour', percentUsed: 63.4 },
    { kind: 'seven_day', percentUsed: 88 },
  ],
}

test('row 2: project and branch quietly, the model in ink, a gauge and both windows in one', async ($, on) => {
  engine(on, WHERE)
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /▣ mait-code/ }))?.props.backgroundColor).toBe(PALETTE.panel)
  expect((await ui.find({ type: 'Text', text: /^opus $/ }))?.props.color).toBe(PALETTE.accent)
  expect((await ui.find({ type: 'Text', text: /^ 142k\/1M $/ }))?.props.backgroundColor).toBe(PALETTE.surface)
  expect((await ui.find({ type: 'Text', text: /^ ▰▱▱▱▱▱▱▱ 14% $/ }))?.props.backgroundColor).toBe(PALETTE.success)
  expect(await ui.find({ type: 'Text', text: /^ 5h·7d $/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^ 63·88% $/ }))?.props.backgroundColor).toBe(PALETTE.error)
  await ui.unmount()
})

test('a detached HEAD shows the short commit', async ($, on) => {
  engine(on, { ...WHERE, branch: null })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /⎇ abc1234/ })).toBeDefined()
  await ui.unmount()
})

test('a model name it does not know is shown as given', async ($, on) => {
  engine(on, { ...WHERE, model: 'my-gateway-model' })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /my-gateway-model/ })).toBeDefined()
  await ui.unmount()
})

test('rate-limit windows hide off a subscription', async ($, on) => {
  engine(on, { ...WHERE, rateLimits: [] })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /5h|7d/ })).toBeUndefined()
  await ui.unmount()
})

test('a measurement updates context and the windows without a turn', async ($, on) => {
  engine(on, WHERE)
  on('session.measure', ($, e) => ({ changed: e.changed }))
  await start($)
  await $.session.measure({
    context: { tokens: 900_000, percent: 90, window: 1_000_000 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 12 }],
    changed: ['context', 'rateLimits'],
  })
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^ 900k\/1M $/ }))).toBeDefined()
  expect((await ui.find({ type: 'Text', text: / 90% $/ }))?.props.backgroundColor).toBe(PALETTE.error)
  expect(await ui.find({ type: 'Text', text: /^ 12% $/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /7d/ })).toBeUndefined()
  await ui.unmount()
})

// --- Jira -------------------------------------------------------------------------

const jiraCard = (id: number, jira: { key: string; url: string | null }[]) => ({ ...card(id), jira })

test('Jira keys sit first on the right, linked ones as buttons that open the browser', async ($, on) => {
  const calls = engine(on, {
    summary: {
      bound: [
        jiraCard(1, [
          { key: 'PLAT-1', url: 'https://acme.atlassian.net/browse/PLAT-1' },
          { key: 'OPS-2', url: null },
        ]),
        jiraCard(2, [{ key: 'PLAT-1', url: 'https://acme.atlassian.net/browse/PLAT-1' }]),
      ],
      in_review: [card(9)],
      inbox: 0,
    },
  })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ jira $/ })).toBeDefined()
  expect(await ui.findAll({ key: 'jira:PLAT-1' })).toHaveLength(1)
  expect(await ui.find({ key: 'jira:OPS-2' })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /^ OPS-2 $/ }))?.props.backgroundColor).toBe(PALETTE.surface)
  expect(await ui.find({ type: 'Text', text: /https:/ })).toBeUndefined()

  await ui.press({ key: 'jira:PLAT-1' })
  expect(calls).toContainEqual(['xdg-open', 'https://acme.atlassian.net/browse/PLAT-1'])
  await ui.unmount()
})

test('a link that is not https is drawn as plain text', async ($, on) => {
  engine(on, { summary: { bound: [jiraCard(1, [{ key: 'X-1', url: 'javascript:alert(1)' }])], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ key: 'jira:X-1' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^ X-1 $/ })).toBeDefined()
  await ui.unmount()
})

test('no Jira block without keys', async ($, on) => {
  engine(on, { summary: { bound: [jiraCard(1, [])], in_review: [], inbox: 0 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /jira/ })).toBeUndefined()
  await ui.unmount()
})

// --- row 3: agents in flight -------------------------------------------------------

type Listed = { id: string; status: string }

/** The engine's side of subagents: spawns answer ids in order, the list is the test's. */
function agentEngine(on: On, listed: Listed[] = []): void {
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: `ag-${++n}` }))
  on('agent.list', () => ({
    value: listed.map(a => ({ ...a, description: 'x', type: 'Explore' })),
  }))
  on('tool.call', () => ({ result: 'ok' }) as never)
  on('turn.complete', () => ({ text: 'done' }))
}

const finish = (agentId?: string) => ({
  answer: 'done', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' as const,
  ...(agentId ? { agentId } : {}),
})

test('a running agent opens row 3, collapsed, and its time moves', async ($, on) => {
  engine(on)
  agentEngine(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  await $.agent.spawn({ prompt: 'look', description: 'Find the hooks', subagentType: 'Explore' })
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...BAR, surface })
    expect(await ui.find({ key: 'agents:toggle' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^  Explore$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^ · 0s $/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Find the hooks/ })).toBeUndefined()
    await ui.unmount()
  }
  await clock.advance(75_000)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ · 1m15s $/ })).toBeDefined()
  await ui.unmount()
})

test('the toggle lists each agent on a line of its own, and folds it again', async ($, on) => {
  engine(on)
  agentEngine(on)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'Find the hooks', subagentType: 'Explore' })
  await $.agent.spawn({ prompt: 'b', description: 'Review the branch', subagentType: 'pre-pr-reviewer' })
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ key: 'agents:toggle' }))?.props.label).toBe('▸ 2 agents')
  await ui.press({ key: 'agents:toggle' })
  expect((await ui.find({ key: 'agents:toggle' }))?.props.label).toBe('▾ 2 agents')
  expect(await ui.find({ type: 'Text', text: /Find the hooks/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Review the branch/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /└/ })).toBeDefined()
  await ui.press({ key: 'agents:toggle' })
  expect(await ui.find({ type: 'Text', text: /Review the branch/ })).toBeUndefined()
  await ui.unmount()
})

test('an agent leaves row 3 when it reports, without a board refresh', async ($, on) => {
  const calls = engine(on)
  agentEngine(on)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'd', subagentType: 'Explore' })
  const before = calls.length
  await $.turn.complete(finish('ag-1'))
  expect(calls.slice(before).some(argv => argv[0] === 'mc-tool-board')).toBe(false)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ key: 'agents:toggle' })).toBeUndefined()
  expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
  await ui.unmount()
})

test('a main turn drops agents the engine finished without a report', async ($, on) => {
  const listed: Listed[] = []
  engine(on)
  agentEngine(on, listed)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'd', subagentType: 'Explore' })
  await $.agent.spawn({ prompt: 'b', description: 'd', subagentType: 'Plan' })
  listed.push({ id: 'ag-1', status: 'killed' }, { id: 'ag-2', status: 'running' })
  await $.turn.complete(finish())
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ key: 'agents:toggle' }))?.props.label).toBe('▸ 1 agent')
  expect(await ui.find({ type: 'Text', text: /Plan/ })).toBeDefined()
  await ui.unmount()
})

test('teammates are left out of row 3', async ($, on) => {
  engine(on)
  agentEngine(on)
  mock.clock(on)
  await start($)
  // Pinned by the engine, so the args type leaves it out; the kit carries it.
  await $.agent.spawn({ prompt: 'a', description: 'd', subagentType: 'Explore', isTeammate: true } as never)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ key: 'agents:toggle' })).toBeUndefined()
  await ui.unmount()
})

test('an open row names the tool each agent last called', async ($, on) => {
  engine(on)
  agentEngine(on)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'd', subagentType: 'Explore' })
  // The loop's id is the engine's to set; the kit carries it as given.
  await $.tool.call({ tool: 'Grep', pattern: 'x', agentId: 'ag-1' } as never)
  await $.tool.call({ tool: 'Read', file_path: '/x', agentId: 'ag-9' } as never)
  await $.tool.call({ tool: 'Bash', command: 'ls' } as never)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  await ui.press({ key: 'agents:toggle' })
  expect(await ui.find({ type: 'Text', text: /^ Grep $/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Read|Bash/ })).toBeUndefined()
  await ui.unmount()
})

test('an agent handing back reads as reporting', async ($, on) => {
  engine(on)
  agentEngine(on)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'd', subagentType: 'Explore' })
  await $.tool.call({ tool: 'SubagentHandback', report: 'x', agentId: 'ag-1' } as never)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  await ui.press({ key: 'agents:toggle' })
  expect(await ui.find({ type: 'Text', text: /^ reporting $/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /SubagentHandback/ })).toBeUndefined()
  await ui.unmount()
})

test('collapsed, row 3 counts agents by type and shows the longest-running time', async ($, on) => {
  engine(on)
  agentEngine(on)
  const clock = mock.clock(on, { now: 0 })
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'd', subagentType: 'Explore' })
  await clock.advance(30_000)
  await $.agent.spawn({ prompt: 'b', description: 'd', subagentType: 'Plan' })
  await $.agent.spawn({ prompt: 'c', description: 'd', subagentType: 'Explore' })
  await clock.advance(42_000)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^  Explore ×2 · Plan$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^ · 1m10s $/ })).toBeDefined()
  await ui.unmount()
})

test('open, agents group under their type, with no heading when all share one', async ($, on) => {
  const world: World = {}
  engine(on, world)
  agentEngine(on)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'First look', subagentType: 'Explore' })
  await $.agent.spawn({ prompt: 'b', description: 'Second look', subagentType: 'Explore' })
  let ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  await ui.press({ key: 'agents:toggle' })
  expect(await ui.find({ key: 'agents:group:Explore' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^First look$/ })).toBeDefined()
  await ui.unmount()

  await $.agent.spawn({ prompt: 'c', description: 'Draft the plan', subagentType: 'Plan' })
  ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ key: 'agents:group:Explore' })).toBeDefined()
  expect(await ui.find({ key: 'agents:group:Plan' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^Draft the plan$/ })).toBeDefined()
  await ui.unmount()
})

// --- row 2: how it says it ---------------------------------------------------------

test('context fills an eight-cell gauge, with tokens over the window as its label', async ($, on) => {
  engine(on, { ...WHERE, context: { tokens: 412_000, percent: 41 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ 412k\/1M $/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^ ▰▰▰▱▱▱▱▱ 41% $/ }))?.props.backgroundColor).toBe(PALETTE.success)
  await ui.unmount()
})

test('both windows share one segment, coloured by the fuller', async ($, on) => {
  engine(on, WHERE)
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^ 63·88% $/ }))?.props.backgroundColor).toBe(PALETTE.error)
  expect(await ui.find({ type: 'Text', text: /^ 5h $/ })).toBeUndefined()
  await ui.unmount()
})

test('a window at 80% or more counts down to its reset', async ($, on) => {
  engine(on, {
    ...WHERE,
    rateLimits: [
      { kind: 'five_hour', percentUsed: 87, resetsAt: new Date(41 * 60_000).toISOString() },
      { kind: 'seven_day', percentUsed: 40, resetsAt: new Date(3 * 86_400_000).toISOString() },
    ],
  })
  mock.clock(on, { now: 0 })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ 87·40% ↻41m $/ })).toBeDefined()
  await ui.unmount()
})

test('the branch carries its changes and its distance from upstream', async ($, on) => {
  const world: World = {
    ...WHERE,
    gitStatus: ['# branch.oid abc', '# branch.head feat/two-rows', '# branch.ab +2 -1', '1 .M x', '? y', '? z'].join('\n'),
  }
  engine(on, world)
  await start($)
  let ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ ⎇ feat\/two-rows ±3 ↑2↓1 $/ })).toBeDefined()
  await ui.unmount()
  world.gitStatus = '# branch.head feat/two-rows\n# branch.ab +0 -0'
  await start($)
  ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ ⎇ feat\/two-rows $/ })).toBeDefined()
  await ui.unmount()
})

// --- badges: each label joined to its value ---------------------------------------

test('in blocks, a label sits on surface beside its value, and badges stand a cell apart', async ($, on) => {
  engine(on, { ...WHERE, summary: { bound: [], in_review: [card(9)], inbox: 2 } })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  for (const label of [/^ in review $/, /^ inbox $/, /^ 5h·7d $/, /^ 142k\/1M $/]) {
    expect((await ui.find({ type: 'Text', text: label }))?.props.backgroundColor).toBe(PALETTE.surface)
  }
  const gaps = await ui.findAll({ type: 'Text', text: /^ $/ })
  expect(gaps.length).toBeGreaterThan(0)
  expect(gaps.every(g => g.props.backgroundColor === PALETTE.panel)).toBe(true)
  await ui.unmount()
})

test('Jira takes the cards\' primary on its label, apart from In Review\'s secondary', async ($, on) => {
  engine(on, {
    summary: { bound: [{ ...card(1), jira: [{ key: 'OPS-2', url: null }] }], in_review: [card(9)], inbox: 0 },
  })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  const label = await ui.find({ type: 'Text', text: /^ jira $/ })
  expect(label?.props.backgroundColor).toBe(PALETTE.primary)
  expect(label?.props.color).toBe(PALETTE.background)
  expect((await ui.find({ type: 'Text', text: /^ OPS-2 $/ }))?.props.backgroundColor).toBe(PALETTE.surface)
  await ui.unmount()
})

test('the windows segment names both windows in its label', async ($, on) => {
  engine(on, WHERE)
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^ 5h·7d $/ })).toBeDefined()
  await ui.unmount()
})

test('no gap cells in slim, where glyphs already part the segments', async ($, on) => {
  engine(on, { ...WHERE, style: 'slim' })
  await start($)
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect(await ui.findAll({ type: 'Text', text: /^ $/ })).toHaveLength(0)
  await ui.unmount()
})


test('the model is coloured text on the panel, never a block, in both styles', async ($, on) => {
  const world: World = { ...WHERE, model: 'claude-sonnet-5-5[1m]', context: undefined }
  engine(on, world)
  for (const style of ['blocks', 'slim']) {
    world.style = style
    await start($)
    const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
    expect((await ui.find({ type: 'Text', text: /^ ✦ $/ }))?.props.color).toBe(PALETTE.accent)
    const family = await ui.find({ type: 'Text', text: /^sonnet $/ })
    expect(family?.props.color).toBe(PALETTE.accent)
    expect(family?.props.backgroundColor).toBe(PALETTE.panel)
    expect((await ui.find({ type: 'Text', text: /^5\.5 $/ }))?.props.color).toBe(PALETTE.foreground)
    expect(await ui.find({ type: 'Text', text: /1M/ })).toBeUndefined()
    await ui.unmount()
  }
})

// --- row 3: the ticker and the engine's list ------------------------------------------

test('agents spawned together start one ticker, and it stops when the last reports', async ($, on) => {
  engine(on)
  agentEngine(on)
  let started = 0
  let cancelled = 0
  on('clock.every', ($, e, next) => {
    started++
    // A period that never resolves stands for a live timer; its abort is the cancel.
    return new Promise((_, reject) => next.signal.addEventListener('abort', () => { cancelled++; reject(new Error('cancelled')) })) as never
  })
  on('clock.now', () => ({ value: 0 }))
  await start($)
  await Promise.all(['a', 'b', 'c'].map(p => $.agent.spawn({ prompt: p, description: 'd', subagentType: 'Explore' })))
  expect(started).toBe(1)
  for (const id of ['ag-1', 'ag-2', 'ag-3']) await $.turn.complete(finish(id))
  expect(cancelled).toBe(started)
})

test('a main turn drops an agent the engine no longer lists, but keeps a workflow\'s', async ($, on) => {
  const listed: Listed[] = []
  engine(on)
  agentEngine(on, listed)
  mock.clock(on)
  await start($)
  await $.agent.spawn({ prompt: 'a', description: 'Gone quietly', subagentType: 'Explore' })
  await $.agent.spawn({ prompt: 'b', description: 'Still going', subagentType: 'Plan' })
  await $.agent.spawn({
    prompt: 'c', description: 'In a workflow', subagentType: 'Explore', workflow: { runId: 'wf_x', agentIndex: 1 },
  } as never)
  listed.push({ id: 'ag-2', status: 'running' })
  await $.turn.complete(finish())
  const ui = await $.ui.mount({ ...BAR, surface: 'terminal' })
  expect((await ui.find({ key: 'agents:toggle' }))?.props.label).toBe('▸ 2 agents')
  await ui.press({ key: 'agents:toggle' })
  expect(await ui.find({ type: 'Text', text: /^Gone quietly$/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^Still going$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^In a workflow$/ })).toBeDefined()
  await ui.unmount()
})
