import { test, expect } from 'claude-code/testing'
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
      rateLimits: [],
    },
  }
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
    { tokens: 120_000, percent: 12, colour: PALETTE.success, text: /120k · 12%/ },
    { tokens: 612_000, percent: 61, colour: PALETTE.warning, text: /612k · 61%/ },
    { tokens: 1_000_000, percent: 80, colour: PALETTE.error, text: /1M · 80%/ },
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
