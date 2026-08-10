import { useState, useCallback, useMemo } from 'react'
import type { MachineState } from '../engine/stateMachine'
import { currentStep, progressPct, canGoBack } from '../engine/stateMachine'
import LessonStep from './steps/LessonStep'
import ShowcaseStep from './steps/ShowcaseStep'
import TaskStep from './steps/TaskStep'
import type { Step } from '../data/types'

interface Props {
  state: MachineState
  onAdvance: () => void
  onBack: () => void
  onSetField: (elementId: string, value: string) => void
  onCanvasAdd: (activityId: string, index?: number) => void
  onCanvasMove: (from: number, to: number) => void
  onCanvasRemove: (index: number) => void
  onRestart: () => void
}

function exitDuration(): number {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 160 : 320
}

/** Chapters in track order, each with the step range it covers. The rail and the
 *  dots count these; the progress bar still counts steps, because that is what a
 *  trainee is actually working through. */
function chaptersOf(steps: Step[]) {
  const out: { name: string; first: number; last: number }[] = []
  steps.forEach((s, i) => {
    const name = s.chapter ?? s.title
    const tail = out[out.length - 1]
    if (tail && tail.name === name) tail.last = i
    else out.push({ name, first: i, last: i })
  })
  return out
}

export default function OnboardingShell({
  state,
  onAdvance,
  onBack,
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
    }, exitDuration())
  }, [onAdvance])

  const chapters = useMemo(() => chaptersOf(state.track.steps), [state.track.steps])

  if (state.trackDone) {
    return <TrackComplete trackName={state.track.name} onRestart={onRestart} onBack={onBack} />
  }

  const isTask = step.type === 'task'
  const total = state.track.steps.length
  const current = state.stepIndex + 1
  const chapterIdx = chapters.findIndex(c => state.stepIndex >= c.first && state.stepIndex <= c.last)

  const stateOf = (i: number) => (i === chapterIdx ? 'current' : i < chapterIdx ? 'done' : 'todo')

  return (
    <div className="h-full flex bg-canvas">
      {/* ── Rail: where you are in the whole thing ─────────────────────────── */}
      <aside className="hidden lg:flex w-[262px] shrink-0 flex-col border-r border-line bg-rail">
        <div className="shrink-0 px-5 pt-5 pb-4">
          <div className="flex items-center gap-2">
            <span className="grid place-items-center w-7 h-7 rounded-control bg-accent text-white font-display font-extrabold text-[14px]">
              P
            </span>
            <span className="text-[14.5px] font-semibold text-ink">Player Journeys</span>
          </div>
        </div>

        <nav className="flex-1 min-h-0 overflow-y-auto px-3 pb-3">
          <p className="mono-label px-2 pb-2">Onboarding journey</p>
          <ul className="flex flex-col gap-0.5">
            {chapters.map((c, i) => (
              <li key={c.name}>
                <div className="rail-item" data-state={stateOf(i)}>
                  <span className="num">{stateOf(i) === 'done' ? '✓' : i + 1}</span>
                  <span className="min-w-0">
                    <span className="nm block">{c.name}</span>
                    <span className="hn block">
                      {c.last > c.first ? `${c.last - c.first + 1} screens` : '1 screen'}
                    </span>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </nav>

        {/* Flick stands here rather than inside the lesson: full height, present
            on every screen, and costing the content area nothing. */}
        <div className="shrink-0 px-4">
          {step.flick && (
            <div className="relative rounded-card border border-line bg-surface px-3 py-2.5">
              <p className="text-[12.5px] text-ink-soft leading-snug">{step.flick.say}</p>
              <span
                className="absolute left-7 -bottom-[7px] w-3 h-3 rotate-45 bg-surface border-b border-r border-line"
                aria-hidden="true"
              />
            </div>
          )}
          <img
            src={`${import.meta.env.BASE_URL}flick/${step.flick?.pose ?? 'teach'}.png`}
            alt="Flick, your guide"
            className="block w-full max-w-[190px] mx-auto -mt-1 select-none pointer-events-none"
            draggable={false}
          />
          <p className="mono-label text-center -mt-2 pb-1">Flick</p>
        </div>

        <div className="shrink-0 px-5 pb-5 pt-3 border-t border-line">
          <p className="mono-label">Your progress</p>
          <p className="text-[12.5px] text-ink-soft mt-1.5">
            {current} of {total} screens
          </p>
          <div className="mt-2 h-1 rounded-full bg-line overflow-hidden">
            <div
              className="h-full bg-accent transition-[width] duration-300"
              style={{ width: `${progressPct(state)}%` }}
            />
          </div>
          <p className="text-[11.5px] text-muted mt-2">~20 min total</p>
        </div>
      </aside>

      {/* ── The screen itself ──────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="shrink-0 h-14 px-5 sm:px-8 border-b border-line bg-surface flex items-center gap-4">
          <div className="flex-1 min-w-0 flex items-center gap-1.5 overflow-hidden">
            {chapters.map((c, i) => (
              <div key={c.name} className="flex items-center gap-1.5 min-w-0">
                {i > 0 && <span className="dot-line" data-state={i <= chapterIdx ? 'done' : 'todo'} />}
                <span className="dot" data-state={stateOf(i)} title={c.name}>
                  {stateOf(i) === 'done' ? '✓' : i + 1}
                </span>
              </div>
            ))}
          </div>
          <span className="mono-label tabular-nums shrink-0">
            {current}&thinsp;/&thinsp;{total}
          </span>
        </header>

        <main className="flex-1 min-h-0 overflow-y-auto px-5 sm:px-8 py-6">
          <div
            key={step.id}
            className={`w-full mx-auto ${isTask ? 'max-w-[1180px]' : 'max-w-wide'} ${
              leaving ? 'animate-step-out' : 'animate-step-in'
            }`}
          >
            {step.type === 'lesson' && <LessonStep step={step} />}
            {step.type === 'showcase' && <ShowcaseStep step={step} />}
            {step.type === 'task' && (
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

        {/* Continue lives here, outside the scrolling area, so it is never
            below the fold. Tasks keep their own gated button instead. */}
        {!isTask && (
          <footer className="shrink-0 px-5 sm:px-8 py-3.5 border-t border-line bg-surface flex items-center gap-3 sm:gap-4">
            <button
              className="btn-ghost shrink-0"
              onClick={onBack}
              disabled={!canGoBack(state)}
            >
              <span aria-hidden="true">←</span> Back
            </button>
            {step.tip ? (
              <div className="flex-1 min-w-0 flex items-center gap-2">
                <img
                  src={`${import.meta.env.BASE_URL}flick/gotit.png`}
                  alt=""
                  className="shrink-0 w-8 h-8 rounded-chip object-cover bg-line-soft"
                />
                <p className="min-w-0 text-[12.5px] text-muted leading-snug">{step.tip}</p>
              </div>
            ) : (
              <span className="flex-1" />
            )}
            <button className="btn-primary shrink-0" onClick={requestAdvance}>
              Continue <span aria-hidden="true">→</span>
            </button>
          </footer>
        )}
      </div>
    </div>
  )
}

// ─── Finish ──────────────────────────────────────────────────────────────────

function TrackComplete({
  trackName,
  onRestart,
  onBack,
}: {
  trackName: string
  onRestart: () => void
  onBack: () => void
}) {
  return (
    <div className="h-full flex flex-col bg-canvas">
      <header className="shrink-0 h-14 px-8 border-b border-line bg-surface flex items-center">
        <span className="mono-label">Growe · CRM Chile</span>
      </header>
      <main className="flex-1 min-h-0 overflow-y-auto flex px-8">
        <div className="w-full max-w-column mx-auto my-auto py-7 animate-step-in">
          <img
            src={`${import.meta.env.BASE_URL}flick/celebrate.png`}
            alt=""
            className="block w-[150px] mb-2 select-none"
            draggable={false}
          />
          <p className="mono-label">Finished</p>
          <h1 className="headline mt-3">That's the whole thing.</h1>
          <p className="lesson-prose mt-5">
            You can read any journey on the canvas, you know which node does what, and you have built
            one from an empty screen. {trackName} is done.
          </p>
          <div className="mt-8 flex items-center gap-3">
            <button className="btn-ghost" onClick={onBack}>
              <span aria-hidden="true">←</span> Back
            </button>
            <button className="btn-primary" onClick={onRestart}>
              Start again
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
