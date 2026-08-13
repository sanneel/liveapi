import type { ReactNode } from 'react'
import { BRAND_OPTIONS } from '../../data/brands'

// ─── The backoffice's own colours ────────────────────────────────────────────
// Green toggles, red required markers: this screen has to be recognisable when
// the trainee meets it for real, so its palette is the product's, not ours.

const PRODUCT_GREEN = '#43A047'
const PRODUCT_INK = '#1F2328'
const PRODUCT_LABEL = '#2B2F33'
const PRODUCT_MUTED = '#9A9E96'
const PRODUCT_LINE = '#D7DAD4'
const PRODUCT_HAIRLINE = '#E8EAE6'

interface Props {
  fieldValues: Record<string, string>
  onSetField: (elementId: string, value: string) => void
}

export const SETTINGS_DEFAULTS: Record<string, string> = {
  'journey-title': 'New Journey - 06.08.2026 15:21',
  'journey-utc': 'utc+4-tbilisi',
  brand: '',
  'launch-mode': 'run-once',
  'journey-start-date': '',
  'start-immediately': 'false',
  'entry-until': '',
  'reentry-rule': 'only-after-exit',
  'entry-max': '10',
  'entry-max-period': 'daily',
  'product-type': '',
  purpose: '',
  'test-control-groups': 'exclude',
  'control-group': 'false',
}

export default function JourneySettings({ fieldValues, onSetField }: Props) {
  const val = (id: string) => fieldValues[id] ?? SETTINGS_DEFAULTS[id] ?? ''
  const startsImmediately = val('start-immediately') === 'true'

  return (
    <div className="surface-card w-full overflow-hidden">
      <div className="px-7 py-7" style={{ color: PRODUCT_INK, fontSize: '15px', lineHeight: 1.5 }}>
        {/* ── Identity ─────────────────────────────────────────────────── */}
        <div className="mb-6">
          <FieldLabel required htmlFor="journey-title">
            Journey title
          </FieldLabel>
          <TextInput
            id="journey-title"
            value={val('journey-title')}
            onChange={v => onSetField('journey-title', v)}
          />
        </div>

        <div className="mb-6">
          <div className="flex items-center gap-1.5 mb-2">
            <FieldLabel htmlFor="journey-utc">Journey UTC</FieldLabel>
            <InfoDot />
          </div>
          <SelectBox
            id="journey-utc"
            value={val('journey-utc')}
            onChange={v => onSetField('journey-utc', v)}
            options={[
              { value: 'utc+4-tbilisi', label: '(UTC +4) Asia/Tbilisi' },
              { value: 'utc-3-santiago', label: '(UTC -3) America/Santiago' },
              { value: 'utc+0-london', label: '(UTC +0) Europe/London' },
            ]}
          />
        </div>

        <div className="mb-6">
          <FieldLabel required htmlFor="brand">
            Brand
          </FieldLabel>
          <SelectBox
            id="brand"
            value={val('brand')}
            placeholder="Select brand"
            onChange={v => onSetField('brand', v)}
            options={BRAND_OPTIONS}
          />
        </div>

        <Divider />

        {/* ── Launch settings ──────────────────────────────────────────── */}
        <SectionHeading>Launch settings</SectionHeading>

        <Segmented
          id="launch-mode"
          value={val('launch-mode')}
          onChange={v => onSetField('launch-mode', v)}
          options={[
            { value: 'run-once', label: 'Run once' },
            { value: 'hourly', label: 'Hourly' },
            { value: 'daily', label: 'Daily' },
            { value: 'weekly', label: 'Weekly' },
            { value: 'monthly', label: 'Monthly' },
            { value: 'yearly', label: 'Yearly' },
          ]}
        />

        <div className="mt-6 flex items-center gap-2 flex-wrap">
          <InlineLabel required>Journey starts on</InlineLabel>
          {/* The product hides the date picker entirely once "start immediately" is on. */}
          {!startsImmediately && (
            <InlineSelect
              id="journey-start-date"
              value={val('journey-start-date')}
              placeholder="Select date"
              onChange={v => onSetField('journey-start-date', v)}
              options={[
                { value: '2026-08-07', label: '07.08.2026 00:00 (UTC +4)' },
                { value: '2026-08-08', label: '08.08.2026 00:00 (UTC +4)' },
              ]}
            />
          )}
        </div>

        <div className="mt-3">
          <Toggle
            id="start-immediately"
            checked={startsImmediately}
            label="Start immediately after publish"
            onChange={next => onSetField('start-immediately', String(next))}
          />
        </div>

        <Divider />

        {/* ── Entry limitation ─────────────────────────────────────────── */}
        <SectionHeading>Entry limitation</SectionHeading>

        <div className="flex items-center gap-2 flex-wrap">
          <InlineLabel required>Player can entry the journey until</InlineLabel>
          <InlineSelect
            id="entry-until"
            value={val('entry-until')}
            placeholder="Select date"
            onChange={v => onSetField('entry-until', v)}
            options={[
              { value: '2026-08-07', label: '07.08.2026 00:00 (UTC +4)' },
              { value: '2026-08-14', label: '14.08.2026 00:00 (UTC +4)' },
            ]}
          />
        </div>

        <div className="mt-4 flex items-center gap-2 flex-wrap">
          <InlineLabel>Player is allowed to re-enter the journey</InlineLabel>
          <InlineSelect
            id="reentry-rule"
            value={val('reentry-rule')}
            onChange={v => onSetField('reentry-rule', v)}
            options={[
              { value: 'only-after-exit', label: 'only after exiting this journey' },
              { value: 'anytime', label: 'at any time' },
              { value: 'never', label: 'never' },
            ]}
          />
          <InfoDot />
        </div>

        <div className="mt-4 flex items-center gap-2 flex-wrap">
          <InlineLabel>Player is allowed to enter the journey maximum</InlineLabel>
          <input
            id="entry-max"
            type="text"
            inputMode="numeric"
            value={val('entry-max')}
            onChange={e => onSetField('entry-max', e.target.value)}
            className="w-10 text-center bg-transparent outline-none rounded"
            style={{ color: PRODUCT_INK }}
          />
          <InlineLabel>time(s)</InlineLabel>
          <InlineSelect
            id="entry-max-period"
            value={val('entry-max-period')}
            onChange={v => onSetField('entry-max-period', v)}
            options={[
              { value: 'daily', label: 'Daily' },
              { value: 'weekly', label: 'Weekly' },
              { value: 'total', label: 'In total' },
            ]}
          />
          <InfoDot />
        </div>

        <Divider />

        {/* ── Product, purpose, control groups ─────────────────────────── */}
        <div className="mb-3">
          <FieldLabel required>Product type</FieldLabel>
        </div>
        <RadioRow
          id="product-type"
          value={val('product-type')}
          onChange={v => onSetField('product-type', v)}
          options={[
            { value: 'sport', label: 'Sport' },
            { value: 'casino', label: 'Casino' },
            { value: 'sport-casino', label: 'Sport & Casino' },
          ]}
        />

        <div className="mt-6 mb-6">
          <FieldLabel required htmlFor="purpose">
            Purpose
          </FieldLabel>
          <SelectBox
            id="purpose"
            value={val('purpose')}
            placeholder="Select purpose"
            onChange={v => onSetField('purpose', v)}
            options={[
              { value: 'marketing-welcome', label: 'Marketing - Welcome' },
              { value: 'marketing-reactivation', label: 'Marketing - Reactivation' },
              { value: 'marketing-retention', label: 'Marketing - Retention' },
              { value: 'crm-vip', label: 'CRM - VIP' },
            ]}
          />
        </div>

        <div className="flex items-center gap-1.5 mb-3">
          <FieldLabel>Players from test control groups</FieldLabel>
          <InfoDot />
        </div>
        <RadioRow
          id="test-control-groups"
          value={val('test-control-groups')}
          onChange={v => onSetField('test-control-groups', v)}
          options={[
            { value: 'exclude', label: 'Exclude all' },
            { value: 'include', label: 'Include all' },
          ]}
        />

        <div
          className="mt-6 rounded-lg px-5 py-4"
          style={{ border: `1px solid ${PRODUCT_HAIRLINE}`, background: '#FCFCFB' }}
        >
          <Toggle
            id="control-group"
            checked={val('control-group') === 'true'}
            label="Control group"
            info
            onChange={next => onSetField('control-group', String(next))}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Primitives ──────────────────────────────────────────────────────────────

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-5" style={{ color: PRODUCT_MUTED, fontSize: '16px' }}>
      {children}
    </h3>
  )
}

function Divider() {
  return <hr className="my-8 border-0 border-t" style={{ borderColor: PRODUCT_HAIRLINE }} />
}

function FieldLabel({
  children,
  required,
  htmlFor,
}: {
  children: ReactNode
  required?: boolean
  htmlFor?: string
}) {
  return (
    <label htmlFor={htmlFor} className="block mb-2" style={{ color: PRODUCT_LABEL }}>
      {children}
      {required && <span style={{ color: '#E23B3B', marginLeft: 2 }}>*</span>}
    </label>
  )
}

function InlineLabel({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <span style={{ color: PRODUCT_LABEL }}>
      {children}
      {required && <span style={{ color: '#E23B3B', marginLeft: 2 }}>*</span>}
    </span>
  )
}

function InfoDot() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke={PRODUCT_MUTED}
      strokeWidth={1.7}
      className="w-[17px] h-[17px] shrink-0"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9.5" />
      <path d="M12 10.6v6" strokeLinecap="round" />
      <circle cx="12" cy="7.4" r="1.1" fill={PRODUCT_MUTED} stroke="none" />
    </svg>
  )
}

function Chevron({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

const boxStyle = { border: `1px solid ${PRODUCT_LINE}` }

function TextInput({
  id,
  value,
  onChange,
}: {
  id: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <input
      id={id}
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full h-12 rounded px-4 bg-white outline-none transition-shadow
                 focus:shadow-[0_0_0_3px_rgba(14,122,90,0.18)]"
      style={{ ...boxStyle, color: PRODUCT_INK, fontSize: '15px' }}
    />
  )
}

interface Option {
  value: string
  label: string
}

function SelectBox({
  id,
  value,
  options,
  placeholder,
  onChange,
}: {
  id: string
  value: string
  options: Option[]
  placeholder?: string
  onChange: (v: string) => void
}) {
  return (
    <div className="relative">
      <select
        id={id}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full h-12 rounded pl-4 pr-10 bg-white outline-none appearance-none
                   cursor-pointer transition-shadow focus:shadow-[0_0_0_3px_rgba(14,122,90,0.18)]"
        style={{ ...boxStyle, color: value ? PRODUCT_INK : PRODUCT_MUTED, fontSize: '15px' }}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map(o => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <Chevron className="w-5 h-5 absolute right-3.5 top-1/2 -translate-y-1/2 pointer-events-none text-[#6E736B]" />
    </div>
  )
}

/** Borderless dropdown that reads as part of a sentence. */
function InlineSelect({
  id,
  value,
  options,
  placeholder,
  onChange,
}: {
  id: string
  value: string
  options: Option[]
  placeholder?: string
  onChange: (v: string) => void
}) {
  const selected = options.find(o => o.value === value)
  return (
    <span className="relative inline-flex items-center">
      <select
        id={id}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="appearance-none bg-transparent outline-none cursor-pointer pr-6 rounded"
        style={{
          color: selected ? PRODUCT_INK : PRODUCT_MUTED,
          fontWeight: selected ? 500 : 400,
          fontSize: '15px',
        }}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map(o => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <Chevron className="w-4 h-4 absolute right-1 top-1/2 -translate-y-1/2 pointer-events-none text-[#6E736B]" />
    </span>
  )
}

function Segmented({
  id,
  value,
  options,
  onChange,
}: {
  id: string
  value: string
  options: Option[]
  onChange: (v: string) => void
}) {
  // Six labels do not fit a phone. Rather than shrink them into each other, the
  // row scrolls — the control keeps the shape it has in the real product.
  return (
    <div id={id} role="radiogroup" className="flex rounded overflow-x-auto">
      {options.map(o => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className="flex-1 shrink-0 min-w-[92px] h-[50px] transition-colors"
            style={{
              background: active ? PRODUCT_GREEN : '#F4F5F3',
              color: active ? '#FFFFFF' : PRODUCT_LABEL,
              fontWeight: active ? 600 : 400,
              fontSize: '15px',
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

function RadioRow({
  id,
  value,
  options,
  onChange,
}: {
  id: string
  value: string
  options: Option[]
  onChange: (v: string) => void
}) {
  return (
    <div id={id} role="radiogroup" className="flex items-center gap-8 flex-wrap rounded py-1">
      {options.map(o => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className="flex items-center gap-2.5 rounded pr-1"
          >
            <span
              className="flex items-center justify-center w-[22px] h-[22px] rounded-full shrink-0"
              style={{ border: `1.5px solid ${active ? PRODUCT_INK : PRODUCT_LINE}` }}
            >
              {active && (
                <span
                  className="w-[11px] h-[11px] rounded-full"
                  style={{ background: PRODUCT_INK }}
                />
              )}
            </span>
            <span style={{ color: PRODUCT_LABEL }}>{o.label}</span>
          </button>
        )
      })}
    </div>
  )
}

function Toggle({
  id,
  checked,
  label,
  info,
  onChange,
}: {
  id: string
  checked: boolean
  label: string
  info?: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className="relative w-[46px] h-[26px] rounded-full shrink-0 transition-colors"
        style={{ background: checked ? PRODUCT_GREEN : '#C9CCC7' }}
      >
        <span
          className="absolute top-[3px] w-5 h-5 rounded-full bg-white transition-all duration-200"
          style={{ left: checked ? '23px' : '3px' }}
        />
      </button>
      <span style={{ color: PRODUCT_LABEL }}>{label}</span>
      {info && <InfoDot />}
    </div>
  )
}
