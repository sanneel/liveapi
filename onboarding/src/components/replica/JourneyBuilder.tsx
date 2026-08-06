import JourneyPalette from './JourneyPalette'
import JourneyCanvas from './JourneyCanvas'
import type { Activity } from '../../data/journeyActivities'

interface Props {
  nodes: string[]
  onAdd: (activityId: string, index?: number) => void
  onMove: (from: number, to: number) => void
  onRemove: (index: number) => void
}

/**
 * The journey builder: palette on the left, canvas on the right, exactly as the
 * real screen is laid out. Nothing here is gated — the trainee assembles what
 * they think the brief asks for, and the checks say whether they are right.
 */
export default function JourneyBuilder({ nodes, onAdd, onMove, onRemove }: Props) {
  const handlePick = (activity: Activity) => onAdd(activity.id)

  return (
    <div className="surface-card overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-line">
        <p className="text-caption font-medium text-ink">Journey builder</p>
        <p className="text-caption text-muted">
          {nodes.length === 0
            ? 'Empty canvas'
            : `${nodes.length} ${nodes.length === 1 ? 'activity' : 'activities'}`}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] divide-y md:divide-y-0 md:divide-x divide-line">
        <div className="p-4">
          <p className="mono-label mb-3">Activities</p>
          <JourneyPalette onAdd={handlePick} />
        </div>

        <div className="p-4 bg-canvas/60">
          <p className="mono-label mb-3">Canvas</p>
          <JourneyCanvas
            nodes={nodes}
            onDrop={(activityId, index) => onAdd(activityId, index)}
            onMove={onMove}
            onRemove={onRemove}
          />
        </div>
      </div>
    </div>
  )
}
