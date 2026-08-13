import type { ReplicaSpec, ReplicaElement } from '../../data/types'
import JourneySettings from './JourneySettings'
import JourneyBuilder from './JourneyBuilder'

interface Props {
  spec: ReplicaSpec
  fieldValues: Record<string, string>
  canvas: string[]
  onSetField: (elementId: string, value: string) => void
  onCanvasAdd: (activityId: string, index?: number) => void
  onCanvasMove: (from: number, to: number) => void
  onCanvasRemove: (index: number) => void
}

export default function ReplicaRenderer({
  spec,
  fieldValues,
  canvas,
  onSetField,
  onCanvasAdd,
  onCanvasMove,
  onCanvasRemove,
}: Props) {
  // Hand-built screens ignore panels/elements and own their own layout.
  if (spec.screen === 'journey-settings') {
    return <JourneySettings fieldValues={fieldValues} onSetField={onSetField} />
  }

  if (spec.screen === 'journey-builder') {
    return (
      <JourneyBuilder
        nodes={canvas}
        onAdd={onCanvasAdd}
        onMove={onCanvasMove}
        onRemove={onCanvasRemove}
      />
    )
  }

  const panels = spec.panels ?? []
  const elements = spec.elements ?? []
  const actions = elements.filter(e => !e.panel && e.type === 'button')

  return (
    <div className="surface-card overflow-hidden">
      <div className="px-6 py-5 border-b border-line">
        <p className="text-caption font-medium text-ink">{spec.screenTitle}</p>
        {spec.screenSubtitle && <p className="text-caption text-muted">{spec.screenSubtitle}</p>}
      </div>

      <div className="divide-y divide-line">
        {panels.map(panel => (
          <section key={panel.id} className="px-6 py-6">
            <p className="mono-label mb-5">{panel.title}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              {elements
                .filter(e => e.panel === panel.id)
                .map(el => (
                  <ElementRenderer
                    key={el.id}
                    element={el}
                    value={fieldValues[el.id] ?? el.defaultValue ?? ''}
                    onSetField={onSetField}
                  />
                ))}
            </div>
          </section>
        ))}

        {actions.length > 0 && (
          <div className="px-6 py-6 flex gap-3 flex-wrap">
            {actions.map(el => (
              <ElementRenderer key={el.id} element={el} value="" onSetField={onSetField} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── One control ─────────────────────────────────────────────────────────────

const FIELD =
  'h-12 w-full rounded-control bg-surface border border-line px-4 text-caption text-ink ' +
  'outline-none transition-shadow placeholder:text-muted ' +
  'focus:border-accent focus:shadow-[0_0_0_3px_rgba(14,122,90,0.18)] ' +
  'disabled:opacity-50 disabled:cursor-not-allowed'

function ElementRenderer({
  element,
  value,
  onSetField,
}: {
  element: ReplicaElement
  value: string
  onSetField: (elementId: string, value: string) => void
}) {
  if (element.type === 'button') {
    // Buttons record that they were pressed, so a check can look for it.
    const pressed = value === 'pressed'
    return (
      <button
        type="button"
        onClick={() => onSetField(element.id, 'pressed')}
        className={
          element.variant === 'primary'
            ? 'btn-primary !text-caption !py-3 !px-6'
            : `inline-flex items-center rounded-control border bg-surface px-6 py-3 text-caption
               transition-colors hover:bg-canvas ${
                 pressed ? 'border-accent text-accent' : 'border-line text-ink'
               }`
        }
      >
        {element.label}
      </button>
    )
  }

  return (
    <div className="col-span-1">
      <label htmlFor={element.id} className="block text-caption text-muted mb-2">
        {element.label}
      </label>

      {element.type === 'select' ? (
        <div className="relative">
          <select
            id={element.id}
            value={value}
            onChange={e => onSetField(element.id, e.target.value)}
            className={`${FIELD} cursor-pointer appearance-none pr-10`}
          >
            {element.options?.map(o => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="w-5 h-5 absolute right-3.5 top-1/2 -translate-y-1/2 pointer-events-none text-muted"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </div>
      ) : (
        <input
          id={element.id}
          type="text"
          disabled={element.readonly}
          placeholder={element.placeholder}
          value={value}
          onChange={e => onSetField(element.id, e.target.value)}
          className={FIELD}
        />
      )}
    </div>
  )
}
