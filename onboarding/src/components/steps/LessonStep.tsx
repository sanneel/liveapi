import { useState, useEffect, useCallback } from 'react'
import type { LessonStep as LessonStepType, ContentBlock, Shot } from '../../data/types'
import OverviewScreen from '../replica/OverviewScreens'

interface Props {
  step: LessonStepType
}

// Media goes in the left column, everything else in the right one. Splitting on
// kind rather than on hand-authored slots means the 22 existing steps did not
// have to be rewritten to get the two-column layout.
const MEDIA: ContentBlock['kind'][] = ['shots', 'screen']

export default function LessonStep({ step }: Props) {
  const [zoom, setZoom] = useState<Shot | null>(null)
  const media = step.content.filter(b => MEDIA.includes(b.kind))
  const rest = step.content.filter(b => !MEDIA.includes(b.kind))

  // The opening paragraph reads as a standfirst under the heading, full width.
  const lede = rest[0]?.kind === 'paragraph' ? rest[0] : null
  const aside = lede ? rest.slice(1) : rest

  return (
    <article>
      {step.eyebrow && <p className="mono-label">{step.eyebrow}</p>}
      <h1 className="headline mt-2">{step.title}</h1>
      {lede && (
        <p
          className="text-lede text-ink-soft mt-3 max-w-[76ch] [&_strong]:font-semibold [&_strong]:text-ink"
          dangerouslySetInnerHTML={{ __html: lede.html }}
        />
      )}

      {media.length > 0 ? (
        <div className="mt-5 grid gap-5 items-start lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4 min-w-0">
            {media.map((b, i) => (
              <ContentBlockRenderer key={i} block={b} onZoom={setZoom} />
            ))}
          </div>
          {aside.length > 0 && (
            <div className="flex flex-col gap-3.5 min-w-0">
              {aside.map((b, i) => (
                <ContentBlockRenderer key={i} block={b} inAside />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="mt-5 max-w-column flex flex-col gap-3.5">
          {aside.map((b, i) => (
            <ContentBlockRenderer key={i} block={b} />
          ))}
        </div>
      )}

      {zoom && <Lightbox shot={zoom} onClose={() => setZoom(null)} />}
    </article>
  )
}

// ─── Full screen ─────────────────────────────────────────────────────────────

/** A screenshot at readable size. Inline the column caps these at about 650px
 *  wide while the captures are 2800px, so the log rows and prize tables are
 *  unreadable until they are opened. */
function Lightbox({ shot, onClose }: { shot: Shot; onClose: () => void }) {
  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose],
  )
  useEffect(() => {
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onKey])

  return (
    <div
      className="fixed inset-0 z-50 bg-ink/85 flex flex-col items-center justify-center gap-3 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={shot.alt}
      onClick={onClose}
    >
      <img
        src={import.meta.env.BASE_URL + shot.src}
        alt={shot.alt}
        className="max-w-full max-h-[84vh] object-contain rounded-card shadow-raised bg-surface"
        onClick={e => e.stopPropagation()}
      />
      {shot.caption && (
        <p className="text-caption text-white/75 max-w-[90ch] text-center">{shot.caption}</p>
      )}
      <button
        className="absolute right-4 top-4 rounded-chip bg-surface/15 hover:bg-surface/25 text-white w-9 h-9 grid place-items-center text-[15px]"
        onClick={onClose}
        aria-label="Close"
      >
        ✕
      </button>
      <p className="text-[11.5px] text-white/50">Click anywhere or press Esc to close</p>
    </div>
  )
}

// ─── Photos ──────────────────────────────────────────────────────────────────

/** One to three captures on a row. In the two-column layout the column is
 *  already narrow, so heights can stay generous. */
function ShotsBlock({ items, onZoom }: { items: Shot[]; onZoom?: (s: Shot) => void }) {
  // Stacked, not side by side. Two photos across a 1.2fr column left each about
  // 315px wide against a 2800px capture, which is why they read as invisible.
  // Full column width plus click-to-open beats fitting them on one row.
  const cap = items.length > 2 ? 'max-h-[26vh]' : items.length === 2 ? 'max-h-[34vh]' : 'max-h-[52vh]'
  return (
    <div className="not-prose flex flex-col gap-3">
      {items.map(shot => (
        <ShotFigure key={shot.src} shot={shot} cap={cap} onZoom={onZoom} />
      ))}
    </div>
  )
}

function ShotFigure({
  shot,
  cap,
  onZoom,
}: {
  shot: Shot
  cap: string
  onZoom?: (s: Shot) => void
}) {
  const [failed, setFailed] = useState(false)
  return (
    <figure className="min-w-0 flex flex-col gap-2">
      {failed ? (
        <div className="rounded-card border border-dashed border-line bg-surface px-4 py-8 text-center">
          <p className="text-caption text-muted">Screenshot not added yet</p>
          <p className="mono-label mt-2">public/{shot.src}</p>
        </div>
      ) : (
        <button
          type="button"
          className="shot-open"
          onClick={() => onZoom?.(shot)}
          aria-label={`Enlarge: ${shot.alt}`}
        >
          {/* w-auto, not w-full. The captures range from 1.04 to 2.90 in aspect,
              so a full-width box plus object-contain letterboxed the squarer ones
              with white bars down both sides. Letting the frame hug the image
              removes the bars at every ratio. */}
          <img
            src={import.meta.env.BASE_URL + shot.src}
            alt={shot.alt}
            loading="lazy"
            onError={() => setFailed(true)}
            className={`block w-auto max-w-full ${cap}`}
          />
          <span className="badge" aria-hidden="true">Click to enlarge</span>
        </button>
      )}
      {shot.caption && (
        <figcaption className="text-caption text-muted leading-snug">{shot.caption}</figcaption>
      )}
    </figure>
  )
}

// ─── Blocks ──────────────────────────────────────────────────────────────────

function ContentBlockRenderer({
  block,
  inAside,
  onZoom,
}: {
  block: ContentBlock
  inAside?: boolean
  onZoom?: (s: Shot) => void
}) {
  switch (block.kind) {
    case 'paragraph':
      return (
        <p
          className="lesson-prose"
          dangerouslySetInnerHTML={{ __html: block.html }}
        />
      )
    case 'shots':
      return <ShotsBlock items={block.items} onZoom={onZoom} />
    case 'screen':
      return (
        <figure className="not-prose">
          <OverviewScreen name={block.name} />
          {block.caption && (
            <figcaption className="text-caption text-muted mt-2 leading-snug">
              {block.caption}
            </figcaption>
          )}
        </figure>
      )
    case 'diagram':
      return inAside ? (
        <div className="pane">
          <p className="pane-title">What happens next?</p>
          <DiagramBlock block={block} />
        </div>
      ) : (
        <DiagramBlock block={block} />
      )
    case 'table':
      return <TableBlock block={block} />
    case 'rule-list':
      return (
        <div className="pane">
          <p className="pane-title">Key takeaway</p>
          <RuleListBlock block={block} />
        </div>
      )
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
