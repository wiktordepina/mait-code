/** A board card as the bar shows it. */
export type Card = { id: number; title: string }

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

/** What the bar shows. */
export type BarData = {
  /** Cards bound to this Claude Code session. */
  bound: readonly Card[]
  /** Cards In Review for the session's project. */
  inReview: readonly Card[]
  inbox: number
  /** The live context window, as the engine reports it; absent until known. */
  context?: { tokens: number; percent: number }
}

/** The `status-bar-style` setting. */
export type BarStyle = 'blocks' | 'slim'

declare module 'claude-code' {
  interface PluginState {
    'mait-companion': {
      data: BarData
      /** `null` until mait-code answers; the bar draws nothing without it. */
      palette: Palette | null
      style: BarStyle
    }
  }
}
