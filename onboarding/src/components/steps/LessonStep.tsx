import type { LessonStep as LessonStepType, ContentBlock } from '../../data/types'
import OverviewScreen from '../replica/OverviewScreens'

interface Props {
  step: LessonStepType
  onContinue: () => void
}

export default function LessonStep({ step, onContinue }: Props) {
  return (
    <article>
      {step.eyebrow && <p className="mono-label">{step.eyebrow}</p>}
      <h1 className="headline mt-5">{step.title}</h1>

      <div className="mt-8 flex flex-col gap-7">
        {step.content.map((block, i) => (
          <ContentBlockRenderer key={i} block={block} />
        ))}
      </div>

      <div className="mt-12">
        <button className="btn-primary" onClick={onContinue}>
          Continue
        </button>
      </div>
    </article>
  )
}

// ─── Content blocks ───────────────────────────────────────────────────────────

function ContentBlockRenderer({ block }: { block: ContentBlock }) {
  switch (block.kind) {
    case 'paragraph':
      return (
        <p
          className="text-body leading-[1.75] text-ink-soft"
          dangerouslySetInnerHTML={{ __html: block.html }}
        />
      )
    case 'screen':
      return (
        <figure className="not-prose">
          <OverviewScreen name={block.name} />
          {block.caption && (
            <figcaption className="text-caption text-muted mt-3 leading-relaxed">
              {block.caption}
            </figcaption>
          )}
        </figure>
      )
    case 'diagram':
      return <DiagramBlock block={block} />
    case 'table':
      return <TableBlock block={block} />
    case 'rule-list':
      return <RuleListBlock block={block} />
    case 'split-card':
      return <SplitCardBlock block={block} />
    default:
      return null
  }
}

// ─── Diagram — three boxes with visible arrow connectors ─────────────────────

function DiagramBlock({ block }: { block: Extract<ContentBlock, { kind: 'diagram' }> }) {
  return (
    <div className="surface-card overflow-hidden">
      <div className="flex flex-col sm:flex-row">
        {block.boxes.map((box, i) => (
          <div key={box.id} className="flex sm:flex-col flex-1">
            {/* Box */}
            <div className="flex-1 p-6">
              <p className="text-caption font-semibold text-ink">{box.label}</p>
              {box.examples && (
                <ul className="mt-3 space-y-1.5">
                  {box.examples.map(ex => (
                    <li key={ex} className="text-caption text-muted leading-snug">
                      {ex}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {/* Arrow connector — appears after every box except the last */}
            {i < block.boxes.length - 1 && (
              <div className="flex items-center justify-center sm:hidden px-2 py-3">
                {/* Mobile: vertical arrow */}
                <svg width="16" height="28" viewBox="0 0 16 28" fill="none" aria-hidden="true">
                  <line x1="8" y1="0" x2="8" y2="20" stroke="#C8CCC6" strokeWidth="1.5" />
                  <path d="M3 16 L8 24 L13 16" stroke="#C8CCC6" strokeWidth="1.5" fill="none"
                    strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            )}
          </div>
        ))}
      </div>
      {/* Desktop: horizontal connector bar */}
      <div className="hidden sm:flex border-t border-line">
        {block.boxes.map((box, i) => (
          <div key={box.id} className="flex-1 flex items-center justify-center py-3 relative">
            <span className="text-label font-mono uppercase tracking-wide text-muted text-[11px]">
              {i === 0 ? 'triggers' : i === 1 ? 'applies logic' : 'delivers'}
            </span>
            {i < block.boxes.length - 1 && (
              <span className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 z-10">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <circle cx="10" cy="10" r="9" fill="white" stroke="#E4E6E0" strokeWidth="1" />
                  <path d="M6 10 L14 10 M10 6 L14 10 L10 14"
                    stroke="#0E7A5A" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Table — definition list, subtle alternating weight ──────────────────────

function TableBlock({ block }: { block: Extract<ContentBlock, { kind: 'table' }> }) {
  return (
    <div className="surface-card overflow-hidden">
      <dl className="divide-y divide-line">
        {block.rows.map((row, i) => (
          <div
            key={row.node}
            className={`px-6 py-5 sm:flex sm:gap-6 transition-colors ${
              i % 2 === 0 ? '' : 'bg-canvas/50'
            }`}
          >
            <dt className="text-caption font-semibold text-ink sm:w-[160px] sm:shrink-0 sm:pt-0.5">
              {row.node}
            </dt>
            <dd className="text-caption text-muted mt-1 sm:mt-0 leading-relaxed">{row.role}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

// ─── Rule list — numbered, accent counter ────────────────────────────────────

function RuleListBlock({ block }: { block: Extract<ContentBlock, { kind: 'rule-list' }> }) {
  return (
    <ol className="surface-card overflow-hidden divide-y divide-line">
      {block.rules.map((rule, i) => (
        <li key={i} className="flex gap-5 px-6 py-5">
          <span
            className="mono-label shrink-0 mt-[3px] w-6 text-right text-accent"
            aria-hidden="true"
          >
            {String(i + 1).padStart(2, '0')}
          </span>
          <div>
            <p className="text-caption font-semibold text-ink leading-snug">{rule.text}</p>
            {rule.sub && (
              <p className="text-caption text-muted mt-1.5 leading-relaxed">{rule.sub}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

// ─── Split card — left accent border distinguishes the two panels ─────────────

const PANEL_ACCENTS = ['#0E7A5A', '#C4913A'] // green = promotion, amber = journey

function SplitCardBlock({ block }: { block: Extract<ContentBlock, { kind: 'split-card' }> }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {([block.left, block.right] as const).map((panel, i) => (
        <div
          key={panel.heading}
          className="surface-card p-6 border-l-[3px]"
          style={{ borderLeftColor: PANEL_ACCENTS[i] }}
        >
          <p className="mono-label">{panel.heading}</p>
          <p className="text-caption font-semibold text-ink mt-3 leading-snug">{panel.title}</p>
          <p className="text-caption text-muted mt-2 leading-relaxed">{panel.body}</p>
        </div>
      ))}
    </div>
  )
}
