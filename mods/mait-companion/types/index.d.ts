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

/** Row 2: where the session is and what it's using. */
export type SessionData = {
  /** The project root's folder name. */
  project?: string
  /** The branch checked out, or the short commit when detached. */
  branch?: string
  model?: string
  /** The live context window, as the engine reports it; absent until known. */
  context?: { tokens: number; percent: number }
  /** The rate-limit windows; absent off a subscription or before a reading. */
  fiveHour?: { percent: number }
  sevenDay?: { percent: number }
}

/** The `status-bar-style` setting. */
export type BarStyle = 'blocks' | 'slim'

declare module 'claude-code' {
  interface PluginState {
    'mait-companion': {
      work: WorkData
      session: SessionData
      /** `null` until mait-code answers; the bar draws nothing without it. */
      palette: Palette | null
      style: BarStyle
    }
  }
}
