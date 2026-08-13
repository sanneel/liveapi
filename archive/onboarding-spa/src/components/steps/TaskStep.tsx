import type { TaskStep as TaskStepType } from '../../data/types'
import type { MachineState } from '../../engine/stateMachine'
import { checkResults, isStepDone } from '../../engine/stateMachine'
import ReplicaRenderer from '../replica/ReplicaRenderer'

interface Props {
  step: TaskStepType
  state: MachineState
  onSetField: (elementId: string, value: string) => void
  onCanvasAdd: (activityId: string, index?: number) => void
  onCanvasMove: (from: number, to: number) => void
  onCanvasRemove: (index: number) => void
  onContinue: () => void
}

export default function TaskStep({
  step,
  state,
  onSetField,
  onCanvasAdd,
  onCanvasMove,
  onCanvasRemove,
  onContinue,
}: Props) {
  const results = checkResults(state)
  const done    = isStepDone(state)
  const passed  = results.filter(r => r.done).length

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-10 lg:gap-14 items-start">

      {/* ── Brief + checks ─────────────────────────────────────────────── */}
      <aside className="lg:sticky lg:top-8">
        {step.eyebrow && <p className="mono-label">{step.eyebrow}</p>}

        <h1
          className="font-display font-extrabold leading-[1.08] text-ink mt-5"
          style={{ fontSize: 'clamp(22px, 3vw, 28px)', letterSpacing: '-0.02em' }}
        >
          {step.title}
        </h1>

        <p className="text-caption text-muted mt-4 leading-[1.7]">{step.brief}</p>

        {/* Check list */}
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <p className="mono-label">Checks</p>
            <span
              className="mono-label tabular-nums"
              style={{ color: done ? 'var(--accent)' : undefined }}
            >
              {passed}/{results.length}
            </span>
          </div>

          <ul className="space-y-2">
            {results.map(r => (
              <li
                key={r.id}
                className={`flex gap-3 items-start px-3 py-2.5 rounded-lg transition-colors duration-300 ${
                  r.done ? 'bg-accent/[0.07]' : 'bg-canvas'
                }`}
              >
                <CheckIcon done={r.done} />
                <span
                  className={`text-caption leading-snug transition-colors duration-300 ${
                    r.done ? 'text-ink' : 'text-muted'
                  }`}
                >
                  {r.label}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-8 hidden lg:block">
          <button
            className="btn-primary w-full justify-center !text-[15px] !py-3"
            onClick={onContinue}
            disabled={!done}
          >
            {done ? 'Continue' : `${passed} of ${results.length} done`}
          </button>
        </div>
      </aside>

      {/* ── The work surface ────────────────────────────────────────────── */}
      <div className="min-w-0">
        <ReplicaRenderer
          spec={step.replica}
          fieldValues={state.fieldValues}
          canvas={state.canvas}
          onSetField={onSetField}
          onCanvasAdd={onCanvasAdd}
          onCanvasMove={onCanvasMove}
          onCanvasRemove={onCanvasRemove}
        />

        <div className="mt-8 lg:hidden">
          <button className="btn-primary" onClick={onContinue} disabled={!done}>
            {done ? 'Continue' : `${passed} of ${results.length} done`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Check tick — animated fill ──────────────────────────────────────────────

function CheckIcon({ done }: { done: boolean }) {
  return (
    <span
      className="mt-[2px] w-[18px] h-[18px] rounded-full shrink-0 flex items-center justify-center
                 transition-all duration-300"
      style={{
        background: done ? 'var(--accent)' : 'transparent',
        border: done ? 'none' : '1.5px solid var(--line)',
      }}
      aria-hidden="true"
    >
      {done && (
        <svg
          viewBox="0 0 24 24" fill="none"
          stroke="white" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"
          className="w-[10px] h-[10px]"
        >
          <path d="m5 13 4 4L19 7" />
        </svg>
      )}
    </span>
  )
}
