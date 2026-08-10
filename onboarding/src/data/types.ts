// ─── Content block types (used inside LessonStep) ───────────────────────────

/** Read-only reproductions of real backoffice screens, used as lesson media. */
export type ScreenName =
  | 'journeys-list'
  | 'promo-list'
  | 'promo-page-form'
  | 'promotions-site'
  // Reproductions of one real spin, captured 07.08.2026 from randomizer
  // RND-0-17731. The account number is deliberately truncated: /admin/onboarding
  // is served by a static mount that does not require login.
  | 'journey-log'
  | 'randomizer-players'
  | 'player-bonus-card'

export type ContentBlock =
  | { kind: 'paragraph'; html: string }
  | { kind: 'screen'; name: ScreenName; caption?: string }
  /**
   * A real screenshot, served as a static file. `src` is relative to the SPA
   * base: a file dropped at onboarding/public/<src> is copied into dist by Vite
   * and served by the /admin/onboarding routes. Renders a labelled slot naming
   * the file until it exists, so a missing capture never ships as a broken image.
   */
  | { kind: 'shot'; src: string; alt: string; caption?: string }
  | { kind: 'diagram'; boxes: DiagramBox[]; arrows: DiagramArrow[] }
  | { kind: 'table'; rows: TableRow[] }
  | { kind: 'rule-list'; rules: Rule[] }
  | { kind: 'split-card'; left: SplitPanel; right: SplitPanel }

export interface DiagramBox {
  id: string
  label: string
  sublabel?: string
  examples?: string[]
}

export interface DiagramArrow {
  from: string
  to: string
}

export interface TableRow {
  node: string
  role: string
  nodeType?: NodeType
  detail?: string
}

export interface Rule {
  text: string
  sub?: string
}

export interface SplitPanel {
  heading: string
  title: string
  body: string
}

// ─── Step types ──────────────────────────────────────────────────────────────

export type NodeType = 'source' | 'wait' | 'cond' | 'reward' | 'comms' | 'exit'

export type StepType = 'lesson' | 'showcase' | 'task'

export interface BaseStep {
  id: string
  type: StepType
  title: string
}

export interface LessonStep extends BaseStep {
  type: 'lesson'
  eyebrow: string
  content: ContentBlock[]
  /** IDs of canvas nodes to highlight during this lesson (left panel) */
  canvasHighlight?: string[]
}

export interface ShowcaseItem {
  id: string
  label: string
  description: string
  nodeType?: NodeType
}

export interface ShowcaseStep extends BaseStep {
  type: 'showcase'
  eyebrow: string
  description: string
  items: ShowcaseItem[]
}

// ─── Replica / Task ──────────────────────────────────────────────────────────

export type ReplicaElementType =
  | 'input'
  | 'select'
  | 'button'
  | 'toggle'
  | 'radio'
  | 'label'
  | 'panel-header'
  | 'divider'

export interface SelectOption {
  value: string
  label: string
}

export interface ReplicaElement {
  id: string
  type: ReplicaElementType
  label: string
  /** panel this element belongs to (for grouping) */
  panel?: string
  /** initial/display value */
  defaultValue?: string
  options?: SelectOption[]
  /** button variant: primary | secondary | danger */
  variant?: 'primary' | 'secondary' | 'danger'
  /** read-only elements that cannot be interacted with */
  readonly?: boolean
  placeholder?: string
}

export interface ReplicaPanel {
  id: string
  title: string
}

/**
 * Which replica to render. 'generic' builds the screen from `panels`/`elements`;
 * the rest are hand-built reproductions of real backoffice screens and ignore
 * those fields entirely.
 */
export type ReplicaScreen =
  | 'generic'
  | 'journey-settings'
  | 'journey-palette'
  | 'journey-builder'

export interface ReplicaSpec {
  id: string
  screenTitle: string
  screenSubtitle?: string
  /** Defaults to 'generic'. */
  screen?: ReplicaScreen
  panels?: ReplicaPanel[]
  elements?: ReplicaElement[]
}

// ─── Tasks are checked, not dictated ─────────────────────────────────────────
//
// A task states its goal once and then gets out of the way. There is no ordered
// instruction list and nothing is gated: the trainee works in whatever order
// they like, and each check simply reports whether the thing it cares about is
// true yet. Continue unlocks when they all are.

/** Everything a check is allowed to look at. */
export interface TaskContext {
  /** Values entered into replica form controls, by element id. */
  fields: Record<string, string>
  /** Activity ids dropped on the journey canvas, in order, top to bottom. */
  canvas: string[]
}

export interface TaskCheck {
  id: string
  /** Stated as the finished condition, e.g. "Brand is JBCL". */
  label: string
  test: (ctx: TaskContext) => boolean
}

export interface TaskStep extends BaseStep {
  type: 'task'
  eyebrow: string
  /** The whole job in a sentence or two. Sits in the left panel. */
  brief: string
  replica: ReplicaSpec
  checks: TaskCheck[]
}

export type Step = LessonStep | ShowcaseStep | TaskStep

// ─── Track ───────────────────────────────────────────────────────────────────

export interface Track {
  id: string
  name: string
  description: string
  steps: Step[]
}
