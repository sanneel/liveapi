import { useState } from 'react'
import { findActivity, ACTIVITY_CATEGORIES } from '../../data/journeyActivities'
import { ActivityIcon } from '../icons/activityIcons'

export const DND_MIME = 'application/x-journey-activity'

interface Props {
  /** Activity ids, top to bottom. */
  nodes: string[]
  onDrop: (activityId: string, index: number) => void
  onMove: (from: number, to: number) => void
  onRemove: (index: number) => void
}

/**
 * The canvas half of the builder: an ordered vertical track. Dropping between
 * two nodes inserts there, so order is something the trainee controls rather
 * than something the app decides for them.
 */
export default function JourneyCanvas({ nodes, onDrop, onMove, onRemove }: Props) {
  // Which gap is currently under the pointer, and which node is being dragged
  // out of the canvas itself (null when the drag came from the palette).
  const [overGap, setOverGap] = useState<number | null>(null)
  const [draggingFrom, setDraggingFrom] = useState<number | null>(null)

  const handleDrop = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    setOverGap(null)
    const from = draggingFrom
    setDraggingFrom(null)

    if (from !== null) {
      onMove(from, index)
      return
    }
    const activityId = e.dataTransfer.getData(DND_MIME)
    if (activityId) onDrop(activityId, index)
  }

  const allowDrop = (e: React.DragEvent, index: number) => {
    // Only claim the drop if it is one of ours.
    if (draggingFrom === null && !e.dataTransfer.types.includes(DND_MIME)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = draggingFrom !== null ? 'move' : 'copy'
    setOverGap(index)
  }

  return (
    <div
      className="flex flex-col"
      onDragLeave={e => {
        // Only clear when the pointer truly leaves the canvas, not on every
        // child boundary crossing.
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setOverGap(null)
      }}
    >
      {nodes.length === 0 && (
        <Gap
          index={0}
          isOver={overGap === 0}
          isEmpty
          onDragOver={allowDrop}
          onDrop={handleDrop}
        />
      )}

      {nodes.map((activityId, i) => (
        <div key={`${activityId}-${i}`}>
          <Gap
            index={i}
            isOver={overGap === i}
            isFirst={i === 0}
            onDragOver={allowDrop}
            onDrop={handleDrop}
          />
          <CanvasNode
            activityId={activityId}
            index={i}
            isLast={i === nodes.length - 1}
            onDragStart={() => setDraggingFrom(i)}
            onDragEnd={() => {
              setDraggingFrom(null)
              setOverGap(null)
            }}
            onRemove={() => onRemove(i)}
          />
        </div>
      ))}

      {nodes.length > 0 && (
        <Gap
          index={nodes.length}
          isOver={overGap === nodes.length}
          isFirst
          onDragOver={allowDrop}
          onDrop={handleDrop}
        />
      )}
    </div>
  )
}

// ─── Drop target between nodes ───────────────────────────────────────────────

function Gap({
  index,
  isOver,
  isEmpty,
  isFirst,
  onDragOver,
  onDrop,
}: {
  index: number
  isOver: boolean
  isEmpty?: boolean
  /**
   * Gaps at either end of the track are drop targets but draw no connector —
   * nothing feeds into the first node, and nothing follows the last.
   */
  isFirst?: boolean
  onDragOver: (e: React.DragEvent, index: number) => void
  onDrop: (e: React.DragEvent, index: number) => void
}) {
  if (isEmpty) {
    return (
      <div
        onDragOver={e => onDragOver(e, index)}
        onDrop={e => onDrop(e, index)}
        className={`rounded-control border-2 border-dashed px-6 py-12 text-center transition-colors ${
          isOver ? 'border-accent bg-accent-weak' : 'border-line'
        }`}
      >
        <p className="text-caption text-muted">Drag an activity here to start the journey.</p>
      </div>
    )
  }

  // Between nodes: a connector so the canvas reads as a flow rather than a
  // list. Under a drag it becomes the insertion bar.
  return (
    <div
      onDragOver={e => onDragOver(e, index)}
      onDrop={e => onDrop(e, index)}
      className="h-7 flex items-center justify-center"
    >
      {isOver ? (
        <span className="w-full h-[3px] rounded bg-accent" />
      ) : isFirst ? (
        <span className="h-full w-px bg-transparent" />
      ) : (
        <span className="relative h-full w-px bg-line flex items-end justify-center">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2.4}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="absolute -bottom-[3px] w-3 h-3 text-line"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      )}
    </div>
  )
}

// ─── One node on the track ───────────────────────────────────────────────────

function CanvasNode({
  activityId,
  index,
  isLast,
  onDragStart,
  onDragEnd,
  onRemove,
}: {
  activityId: string
  index: number
  isLast: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onRemove: () => void
}) {
  const activity = findActivity(activityId)
  if (!activity) return null
  const category = ACTIVITY_CATEGORIES.find(c => c.id === activity.category)

  return (
    <div
      draggable
      onDragStart={e => {
        e.dataTransfer.effectAllowed = 'move'
        // Firefox refuses to start a drag with an empty payload.
        e.dataTransfer.setData('text/plain', activityId)
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      className="group flex items-center gap-3 rounded-control border border-line bg-surface
                 px-3 py-2.5 cursor-grab active:cursor-grabbing"
    >
      <span
        className={`flex items-center justify-center w-9 h-9 shrink-0 ${category?.tile} ${
          category?.glyph
        } ${category?.shape === 'circle' ? 'rounded-full' : 'rounded-lg'}`}
      >
        <ActivityIcon name={activity.icon} className="w-5 h-5" />
      </span>

      <span className="text-caption text-ink flex-1 min-w-0">{activity.label}</span>

      <span className="mono-label shrink-0">{isLast ? 'end' : String(index + 1).padStart(2, '0')}</span>

      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${activity.label}`}
        className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-muted
                   opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:bg-canvas
                   transition-opacity"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          className="w-4 h-4"
          aria-hidden="true"
        >
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  )
}
