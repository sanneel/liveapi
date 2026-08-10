import { useState, useCallback } from 'react'
import type { MachineState } from '../engine/stateMachine'
import { currentStep, progressPct } from '../engine/stateMachine'
import { capture } from '../engine/capture'
import LessonStep from './steps/LessonStep'
import ShowcaseStep from './steps/ShowcaseStep'
import TaskStep from './steps/TaskStep'

interface Props {
  state: MachineState
  onAdvance: () => void
  onSetField: (elementId: string, value: string) => void
  onCanvasAdd: (activityId: string, index?: number) => void
  onCanvasMove: (from: number, to: number) => void
  onCanvasRemove: (index: number) => void
  onRestart: () => void
}

function exitDuration(): number {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 160 : 320
}

export default function OnboardingShell({
  state,
  onAdvance,
  onSetField,
  onCanvasAdd,
  onCanvasMove,
  onCanvasRemove,
  onRestart,
}: Props) {
  const [leaving, setLeaving] = useState(false)
  const step = currentStep(state)

  const requestAdvance = useCallback(() => {
    setLeaving(true)
    window.setTimeout(() => {
      onAdvance()
      setLeaving(false)
      window.scrollTo({ top: 0 })
    }, exitDuration())
  }, [onAdvance])

  if (state.trackDone) {
    return <TrackComplete trackName={state.track.name} onRestart={onRestart} />
  }

  const isTask = step.type === 'task'
  const total  = state.track.steps.length
  const current = state.stepIndex + 1

  return (
    <div className="h-full flex flex-col bg-canvas">
      <ProgressBar pct={progressPct(state)} />

      {/* Shell header — brand left, position right */}
      <header className="shrink-0 px-6 pt-5 pb-0 sm:px-10 flex items-center justify-between">
        <span className="mono-label">Growe · CRM Chile</span>
        <span className="mono-label tabular-nums">{current}&thinsp;/&thinsp;{total}</span>
      </header>

      {/* min-h-0 lets flex-1 actually shrink, so a tall step is bounded by the
          viewport instead of growing the page. py was 10vh top AND bottom, which
          pushed every image step off-screen; the step is still centred by my-auto. */}
      <main className="flex-1 min-h-0 overflow-y-auto flex px-6 sm:px-10">
        <div
          key={step.id}
          className={`w-full mx-auto ${
            isTask ? 'max-w-[1180px] my-auto py-7' : 'max-w-column h-full py-5'
          } ${leaving ? 'animate-step-out' : 'animate-step-in'}`}
        >
          {step.type === 'lesson'   && <LessonStep   step={step} onContinue={requestAdvance} />}
          {step.type === 'showcase' && <ShowcaseStep step={step} onContinue={requestAdvance} />}
          {step.type === 'task'     && (
            <TaskStep
              step={step}
              state={state}
              onSetField={onSetField}
              onCanvasAdd={onCanvasAdd}
              onCanvasMove={onCanvasMove}
              onCanvasRemove={onCanvasRemove}
              onContinue={requestAdvance}
            />
          )}
        </div>
      </main>
    </div>
  )
}

// ─── Progress bar — 2 px, no numbers, just movement ──────────────────────────

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div
      className="fixed inset-x-0 top-0 z-20 h-[2px]"
      style={{ background: 'rgba(14,122,90,.12)' }}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Progress"
    >
      <div
        className="h-full transition-[width] duration-500 ease-out"
        style={{ width: `${pct}%`, background: '#0E7A5A' }}
      />
    </div>
  )
}

// ─── Track complete ───────────────────────────────────────────────────────────

function TrackComplete({ trackName, onRestart }: { trackName: string; onRestart: () => void }) {
  return (
    <div className="h-full flex flex-col bg-canvas">
      <ProgressBar pct={100} />
      <header className="shrink-0 px-6 pt-5 sm:px-10 flex items-center justify-between">
        <span className="mono-label">Growe · CRM Chile</span>
      </header>
      <main className="flex-1 min-h-0 overflow-y-auto flex px-6 sm:px-10">
        <div className="w-full max-w-column mx-auto my-auto py-7 animate-step-in">
          <p className="mono-label">Finished</p>
          <h1 className="headline mt-6">That's the whole thing.</h1>
          <p className="text-body text-ink-soft mt-8 leading-[1.7]">
            You can read any journey on the canvas, you know which node does what,
            and you've built one end to end in the backoffice.
          </p>
          <p className="text-body text-ink-soft mt-4 leading-[1.7]">
            {trackName} is complete. The next journey you open will be a real one.
          </p>
          <div className="mt-12">
            <button
              className="btn-primary"
              onClick={() => { capture('track.restart', { trackName }); onRestart() }}
            >
              Start over
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
