// ─── Forward-only state machine ──────────────────────────────────────────────
//
// Holds which track, which step, the values typed into replica forms, and what
// has been dropped on the journey canvas. It only moves forward.
//
// Note what it does NOT hold: any notion of "the current instruction". Tasks are
// judged by their checks against the state as it stands, so the trainee can do
// the work in any order and nothing has to be replayed or unwound.

import type { Track, Step, TaskContext } from '../data/types'
import { capture } from './capture'

export interface MachineState {
  track: Track
  stepIndex: number
  /** Values entered into replica form controls, by element id. */
  fieldValues: Record<string, string>
  /** Activity ids dropped on the journey canvas, in order. */
  canvas: string[]
  trackDone: boolean
}

// ─── Factory ─────────────────────────────────────────────────────────────────

export function createMachine(track: Track): MachineState {
  capture('track.start', { trackId: track.id })
  return {
    track,
    stepIndex: 0,
    fieldValues: {},
    canvas: [],
    trackDone: false,
  }
}

// ─── Selectors ───────────────────────────────────────────────────────────────

export function currentStep(state: MachineState): Step {
  return state.track.steps[state.stepIndex]
}

export function taskContext(state: MachineState): TaskContext {
  return { fields: state.fieldValues, canvas: state.canvas }
}

/** Which of the current step's checks pass right now. */
export function checkResults(state: MachineState): { id: string; label: string; done: boolean }[] {
  const step = currentStep(state)
  if (step.type !== 'task') return []
  const ctx = taskContext(state)
  return step.checks.map(c => ({ id: c.id, label: c.label, done: c.test(ctx) }))
}

/** Reading steps are done on arrival; task steps when every check passes. */
export function isStepDone(state: MachineState): boolean {
  const step = currentStep(state)
  if (step.type !== 'task') return true
  const ctx = taskContext(state)
  return step.checks.every(c => c.test(ctx))
}

export function progressPct(state: MachineState): number {
  const total = state.track.steps.length
  return Math.round(((state.stepIndex + (isStepDone(state) ? 1 : 0)) / total) * 100)
}

// ─── Actions — return a NEW state (immutable) ────────────────────────────────

/** Advance to the next step (only allowed once the current one is done). */
export function advance(state: MachineState): MachineState {
  if (!isStepDone(state)) return state
  const nextIndex = state.stepIndex + 1

  if (nextIndex >= state.track.steps.length) {
    capture('track.complete', { trackId: state.track.id })
    return { ...state, trackDone: true }
  }

  const nextStep = state.track.steps[nextIndex]
  capture('step.enter', { stepId: nextStep.id, stepType: nextStep.type })

  return { ...state, stepIndex: nextIndex }
}

/** Record a field value change (replica form controls). */
export function setFieldValue(
  state: MachineState,
  elementId: string,
  value: string,
): MachineState {
  return { ...state, fieldValues: { ...state.fieldValues, [elementId]: value } }
}

// ─── Canvas ──────────────────────────────────────────────────────────────────

/** Append an activity, or insert it at `index` when dropped between two nodes. */
export function addToCanvas(
  state: MachineState,
  activityId: string,
  index?: number,
): MachineState {
  const next = [...state.canvas]
  next.splice(index ?? next.length, 0, activityId)
  capture('canvas.add', { activityId, index: index ?? next.length - 1 })
  return { ...state, canvas: next }
}

export function removeFromCanvas(state: MachineState, index: number): MachineState {
  const next = state.canvas.filter((_, i) => i !== index)
  capture('canvas.remove', { index })
  return { ...state, canvas: next }
}

/** Move the node at `from` so it sits at position `to`. */
export function moveOnCanvas(state: MachineState, from: number, to: number): MachineState {
  if (from === to) return state
  const next = [...state.canvas]
  const [moved] = next.splice(from, 1)
  next.splice(from < to ? to - 1 : to, 0, moved)
  return { ...state, canvas: next }
}

export function clearCanvas(state: MachineState): MachineState {
  return { ...state, canvas: [] }
}
