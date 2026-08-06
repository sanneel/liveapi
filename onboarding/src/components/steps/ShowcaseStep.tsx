import { useState } from 'react'
import type { ShowcaseStep as ShowcaseStepType } from '../../data/types'

interface Props {
  step: ShowcaseStepType
  onContinue: () => void
}

export default function ShowcaseStep({ step, onContinue }: Props) {
  const [openId, setOpenId] = useState<string | null>(step.items[0]?.id ?? null)

  return (
    <article>
      {step.eyebrow && <p className="mono-label">{step.eyebrow}</p>}
      <h1 className="headline mt-5">{step.title}</h1>
      <p className="text-body text-ink-soft mt-7 leading-[1.75]">{step.description}</p>

      <ol className="surface-card mt-8 overflow-hidden divide-y divide-line">
        {step.items.map((item, i) => {
          const isOpen = item.id === openId
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => setOpenId(isOpen ? null : item.id)}
                aria-expanded={isOpen}
                className={`w-full text-left px-6 py-5 flex gap-5 items-baseline
                  transition-colors duration-150 group
                  ${isOpen ? 'bg-[#F9FAF8]' : 'hover:bg-canvas/60'}`}
              >
                <span
                  className={`mono-label shrink-0 tabular-nums transition-colors duration-150 ${
                    isOpen ? 'text-accent' : 'group-hover:text-ink-soft'
                  }`}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span
                  className={`text-caption transition-colors duration-150 ${
                    isOpen ? 'text-ink font-semibold' : 'text-ink-soft group-hover:text-ink'
                  }`}
                >
                  {item.label}
                </span>
                {/* Chevron */}
                <span className="ml-auto shrink-0 self-center">
                  <svg
                    viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
                    className={`w-4 h-4 text-muted transition-transform duration-200 ${
                      isOpen ? 'rotate-180' : ''
                    }`}
                    aria-hidden="true"
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </span>
              </button>
              {isOpen && (
                <div className="border-l-[3px] border-accent mx-6 mb-5 pl-5">
                  <p className="text-caption text-muted leading-relaxed">{item.description}</p>
                </div>
              )}
            </li>
          )
        })}
      </ol>

      <div className="mt-12">
        <button className="btn-primary" onClick={onContinue}>
          Continue
        </button>
      </div>
    </article>
  )
}
