import { useState, useCallback } from 'react'
import {
  createMachine,
  advance,
  goBack,
  setFieldValue,
  addToCanvas,
  moveOnCanvas,
  removeFromCanvas,
} from './engine/stateMachine'
import type { MachineState } from './engine/stateMachine'
import OnboardingShell from './components/OnboardingShell'
import crmChile from './data/tracks/crm-chile'

export default function App() {
  const [state, setState] = useState<MachineState>(() => createMachine(crmChile))

  const handleAdvance = useCallback(() => setState(s => advance(s)), [])
  const handleBack = useCallback(() => setState(s => goBack(s)), [])

  const handleSetField = useCallback((elementId: string, value: string) => {
    setState(s => setFieldValue(s, elementId, value))
  }, [])

  const handleCanvasAdd = useCallback((activityId: string, index?: number) => {
    setState(s => addToCanvas(s, activityId, index))
  }, [])

  const handleCanvasMove = useCallback((from: number, to: number) => {
    setState(s => moveOnCanvas(s, from, to))
  }, [])

  const handleCanvasRemove = useCallback((index: number) => {
    setState(s => removeFromCanvas(s, index))
  }, [])

  const handleRestart = useCallback(() => setState(createMachine(crmChile)), [])

  return (
    <OnboardingShell
      state={state}
      onAdvance={handleAdvance}
      onBack={handleBack}
      onSetField={handleSetField}
      onCanvasAdd={handleCanvasAdd}
      onCanvasMove={handleCanvasMove}
      onCanvasRemove={handleCanvasRemove}
      onRestart={handleRestart}
    />
  )
}
