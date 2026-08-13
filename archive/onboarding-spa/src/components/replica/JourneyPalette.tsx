import { useState } from 'react'
import { ACTIVITY_CATEGORIES, activitiesIn } from '../../data/journeyActivities'
import type { Activity, ActivityCategory } from '../../data/journeyActivities'
import { ActivityIcon } from '../icons/activityIcons'
import { DND_MIME } from './JourneyCanvas'

interface Props {
  /** Click fallback — HTML5 drag does not exist on touch, and not everyone uses a mouse. */
  onAdd: (activity: Activity) => void
}

/**
 * The activity sidebar of the journey builder. Tiles are draggable onto the
 * canvas and clickable as a fallback. Category tints are the product's own —
 * they are the grouping a trainee has to recognise later, so they live inside
 * this card and nowhere else in the app.
 */
export default function JourneyPalette({ onAdd }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const toggle = (id: string) =>
    setCollapsed(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  return (
    <div className="max-h-[560px] overflow-y-auto pr-1">
      {ACTIVITY_CATEGORIES.map(category => (
        <CategoryBlock
          key={category.id}
          category={category}
          isCollapsed={collapsed.has(category.id)}
          onToggle={() => toggle(category.id)}
          onAdd={onAdd}
        />
      ))}
    </div>
  )
}

function CategoryBlock({
  category,
  isCollapsed,
  onToggle,
  onAdd,
}: {
  category: ActivityCategory
  isCollapsed: boolean
  onToggle: () => void
  onAdd: (activity: Activity) => void
}) {
  return (
    <section className="mb-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        className="flex items-center gap-1.5 w-full py-2 text-left text-caption text-muted
                   hover:text-ink-soft transition-colors"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`w-3.5 h-3.5 shrink-0 transition-transform duration-200 ${
            isCollapsed ? 'rotate-180' : ''
          }`}
          aria-hidden="true"
        >
          <path d="m5 15 7-7 7 7" />
        </svg>
        {category.label}
      </button>

      {!isCollapsed && (
        <div className="grid grid-cols-3 gap-x-2 gap-y-3 pb-3">
          {activitiesIn(category.id).map(activity => (
            <ActivityTile
              key={activity.id}
              activity={activity}
              category={category}
              onAdd={() => onAdd(activity)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function ActivityTile({
  activity,
  category,
  onAdd,
}: {
  activity: Activity
  category: ActivityCategory
  onAdd: () => void
}) {
  return (
    <button
      id={activity.id}
      type="button"
      draggable
      onDragStart={e => {
        e.dataTransfer.effectAllowed = 'copy'
        e.dataTransfer.setData(DND_MIME, activity.id)
        // Firefox needs a text/plain payload or the drag never starts.
        e.dataTransfer.setData('text/plain', activity.label)
      }}
      onClick={onAdd}
      title={`${activity.label} — drag onto the canvas, or click to add`}
      className="group flex flex-col items-center gap-1.5 cursor-grab active:cursor-grabbing"
    >
      <span
        className={`
          flex items-center justify-center w-[52px] h-[52px] transition-transform duration-150
          ${category.tile} ${category.glyph}
          ${category.shape === 'circle' ? 'rounded-full' : 'rounded-xl'}
          group-hover:scale-[1.05] group-active:scale-95
        `}
      >
        <ActivityIcon name={activity.icon} className="w-6 h-6" />
      </span>
      <span className="text-[10.5px] leading-[1.25] text-ink text-center px-0.5">
        {activity.label}
      </span>
    </button>
  )
}
