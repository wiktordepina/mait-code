/** A Jira issue on a card; `href` is null when the bar can't link it. */
export type JiraRef = { key: string; href: string | null }

/** A board card as the bar shows it. */
export type Card = { id: number; title: string }

/** A card bound to this session, with its Jira references. */
export type BoundCard = Card & { jira: readonly JiraRef[] }

/** The colour roles the bar draws with: `mait-code settings get theme --palette`. */
export type Palette = {
  primary: string
  secondary: string
  accent: string
  foreground: string
  background: string
  surface: string
  panel: string
  success: string
  warning: string
  error: string
}

/** Row 1: the work in hand and what's waiting on you. */
export type WorkData = {
  /** Cards bound to this Claude Code session. */
  bound: readonly BoundCard[]
  /** Cards In Review for the session's project. */
  inReview: readonly Card[]
  inbox: number
}

/** A rate-limit window: how full, and how long until it resets when the engine says. */
export type RateWindow = { percent: number; resetsInMs?: number }

/** Row 2: where the session is and what it's using. */
export type SessionData = {
  /** The project root's folder name. */
  project?: string
  /** The branch checked out, or the short commit when detached. */
  branch?: string
  model?: string
  /** The model id as the engine gives it, which the bar splits into family and version. */
  modelId?: string
  /** Uncommitted changes in the working tree; 0 or absent when clean. */
  dirty?: number
  /** Commits ahead of and behind the upstream; absent without one. */
  ahead?: number
  behind?: number
  /** The live context window, as the engine reports it; absent until known. */
  context?: { tokens: number; percent: number; window?: number }
  /** The rate-limit windows; absent off a subscription or before a reading. */
  fiveHour?: RateWindow
  sevenDay?: RateWindow
}

/** A subagent this session started that has not reported back yet. */
export type AgentRun = {
  /** The id its loop's events carry as `agentId`. */
  id: string
  /** The agent type (`Explore`, `pre-pr-reviewer`, ...). */
  type: string
  /** The Agent call's few-word description of the task. */
  description: string
  /** Epoch milliseconds, when it started. */
  startedAt: number
  /** The tool it last called, once it has called one. */
  lastTool?: string
  /** Started by a workflow script, whose agents `$.agent.list()` never names. */
  workflow?: true
}

/** Row 3: what is live right now; the row exists only while something is. */
export type EventData = {
  agents: readonly AgentRun[]
}

/** The `status-bar-style` setting. */
export type BarStyle = 'blocks' | 'slim'

declare module 'claude-code' {
  interface PluginState {
    'mait-companion': {
      work: WorkData
      session: SessionData
      events: EventData
      /** Whether row 3 lists each agent on a line of its own. */
      agentsOpen: boolean
      /** Epoch milliseconds, ticked while agents run so their elapsed time moves. */
      now: number
      /** `null` until mait-code answers; the bar draws nothing without it. */
      palette: Palette | null
      style: BarStyle
    }
  }
}
