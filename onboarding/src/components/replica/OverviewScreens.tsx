import type { ScreenName } from '../../data/types'

// ─── Read-only reproductions of two backoffice screens ───────────────────────
//
// These illustrate; they are never interactive. Restrained on purpose: the real
// tables carry seven columns, these carry four, because the point is "here is
// where this lives", not a pixel copy. Product chrome (the black nav rail, the
// green Create new button) is reproduced so the screen is recognisable.

const PRODUCT_GREEN = '#1E9E52'
const NAV_INK = '#111315'

export default function OverviewScreen({ name }: { name: ScreenName }) {
  switch (name) {
    case 'journeys-list':
      return <JourneysList />
    case 'promo-list':
      return <PromoList />
    case 'promo-page-form':
      return <PromoPageForm />
    case 'promotions-site':
      return <PromotionsSite />
  }
}

// ─── The promo page form, and the field that does the wiring ─────────────────

function PromoPageForm() {
  return (
    <ScreenFrame>
      <div className="px-5 py-5" style={{ fontSize: '11.5px', color: '#1F2328' }}>
        <FormSection label="Brand, currency" required>
          <p style={{ color: '#8A8F86', fontSize: '10.5px' }} className="mb-1">
            Brand
          </p>
          <FakeSelect value="JBCL" />
          <p style={{ color: '#8A8F86', fontSize: '10.5px' }} className="mt-3 mb-1">
            Currency
          </p>
          <span className="inline-flex items-center gap-2">
            <span
              className="w-4 h-4 rounded-sm flex items-center justify-center"
              style={{ border: '1.5px solid #1F2328' }}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="#1F2328" strokeWidth={3.5} className="w-2.5 h-2.5">
                <path d="m5 13 4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            CLP
          </span>
        </FormSection>

        <FormSection label="Link to promo" required>
          <p style={{ color: '#8A8F86', fontSize: '10.5px' }} className="mb-1">
            Promo Page URL
          </p>
          <FakeInput value="https://jugabet.cl/services/promo/offers/promoPage/5d4a7950…" readOnly />
          <p style={{ color: '#8A8F86', fontSize: '10.5px' }} className="mt-3 mb-1">
            Promo Page deep link
          </p>
          <FakeInput value="app-7fb82c81://nativeapp?campaign_permanent=false&campaig…" readOnly />
        </FormSection>

        {/* The one field this whole lesson is about. */}
        <div className="rounded-control px-4 py-4 -mx-1" style={{ background: '#E3F1EC' }}>
          <p className="mb-3" style={{ color: '#8A8F86', fontSize: '10.5px' }}>
            Journey Builder connection <span style={{ color: '#E23B3B' }}>*</span>
          </p>
          <div
            className="rounded px-3 py-2 mb-3 flex gap-2 items-start"
            style={{ background: '#FDF6E3', color: '#7A5F1E', fontSize: '10.5px' }}
          >
            <span aria-hidden="true">⚠</span>
            Please ensure the journey&apos;s end date is relevant for this promo page
          </div>
          <p style={{ color: '#8A8F86', fontSize: '10.5px' }} className="mb-1">
            Journey ID
          </p>
          <FakeSelect value="JRN-0-639700 JBCL | CS | RB - Game of the week | 50 FS" />
        </div>

        <div className="mt-5">
          <span
            className="inline-block rounded px-5 py-2"
            style={{ border: '1px solid #D7DAD4', fontSize: '11px' }}
          >
            Next
          </span>
        </div>
      </div>
    </ScreenFrame>
  )
}

function FormSection({
  label,
  required,
  children,
}: {
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="pb-5 mb-5 border-b" style={{ borderColor: '#EFF0ED' }}>
      <p className="mb-2" style={{ color: '#8A8F86', fontSize: '10.5px' }}>
        {label} {required && <span style={{ color: '#E23B3B' }}>*</span>}
      </p>
      {children}
    </div>
  )
}

function FakeInput({ value, readOnly }: { value: string; readOnly?: boolean }) {
  return (
    <div
      className="rounded px-3 py-2 truncate"
      style={{
        border: '1px solid #D7DAD4',
        background: readOnly ? '#F4F5F3' : '#FFFFFF',
        color: readOnly ? '#6E736B' : '#1F2328',
      }}
    >
      {value}
    </div>
  )
}

function FakeSelect({ value }: { value: string }) {
  return (
    <div
      className="rounded px-3 py-2 flex items-center justify-between gap-2"
      style={{ border: '1px solid #D7DAD4', background: '#FFFFFF' }}
    >
      <span className="truncate">{value}</span>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="#6E736B"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="w-3.5 h-3.5 shrink-0"
        aria-hidden="true"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </div>
  )
}

// ─── What the player sees ────────────────────────────────────────────────────

const SITE_CARDS = [
  { tag: 'PAQUETE DE BONI…', tagBg: '#C8A165', left: '8H 20M', title: 'Copas Europeas: 10% de apuesta gratis', cta: 'Participate' },
  { tag: 'DEPORTES', tagBg: '#4FC3F7', left: '1D 14H', title: 'Desafío National Bank Open', cta: 'Juega Ahora' },
  { tag: 'DEPORTES', tagBg: '#4FC3F7', left: '3D 14H', title: 'Desafío de Latinoamérica', cta: 'Juega Ahora' },
  { tag: 'CASINO', tagBg: '#F06292', left: '6D 17H', title: 'Elige: 20 o 25 Giros Gratis diarios', cta: 'Juega Ahora' },
]

function PromotionsSite() {
  return (
    <ScreenFrame>
      <div className="p-5" style={{ background: '#1B2A4C' }}>
        <p className="mb-4" style={{ color: '#FFFFFF', fontSize: '13px', fontWeight: 600 }}>
          Bonificaciones
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SITE_CARDS.map(card => (
            <div key={card.title} className="rounded-lg overflow-hidden" style={{ background: '#0F1A33' }}>
              <div className="px-3 pt-3 pb-4">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span
                    className="px-1.5 py-0.5 rounded-sm"
                    style={{ background: card.tagBg, color: '#0F1A33', fontSize: '8.5px', fontWeight: 700 }}
                  >
                    {card.tag}
                  </span>
                  <span style={{ color: '#C3F53C', fontSize: '8.5px', fontWeight: 600 }}>
                    ◷ {card.left} RESTANTES
                  </span>
                </div>
                <p style={{ color: '#FFFFFF', fontSize: '12px', fontWeight: 600, lineHeight: 1.3 }}>
                  {card.title}
                </p>
              </div>

              {/* This row is the door. Tapping it is what enters the journey. */}
              <div
                className="px-3 py-2.5 flex items-center justify-between"
                style={{ borderTop: '1px solid rgba(255,255,255,.07)' }}
              >
                <span>
                  <span style={{ color: '#FFFFFF', fontSize: '11px', fontWeight: 600 }}>
                    {card.cta}
                  </span>
                  <span style={{ color: '#8FA3C8', fontSize: '9.5px' }} className="block">
                    y gana un premio
                  </span>
                </span>
                <span style={{ color: '#6FA8DC', fontSize: '13px' }} aria-hidden="true">
                  ›
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </ScreenFrame>
  )
}

// ─── Journey builder ─────────────────────────────────────────────────────────

const NAV = [
  'Dashboard',
  'Journey builder',
  'Engagement',
  'Loyalty programs',
  'Content Studio',
  'Segments',
  'AI',
]

const JOURNEY_ROWS = [
  { status: 'Running', tone: PRODUCT_GREEN, name: 'JBCL | CS | Torneo Suerte Loca 06.08-13.08', brand: '.jbcl', until: '13.08.2026' },
  { status: 'Planned', tone: '#E0A33E', name: 'JBCL | CS&SP | Torneo Suerte Loca 06.08-13.08', brand: '.jbcl', until: '13.08.2026' },
  { status: 'Running', tone: PRODUCT_GREEN, name: 'PMCL | SP | Regular Weekend SP Promotion w19', brand: '.pmcl', until: '09.08.2026' },
  { status: 'Running', tone: PRODUCT_GREEN, name: 'JBCOM | Giveaway 20.000 Free Bet 05.08', brand: '.jbcom', until: '31.08.2026' },
  { status: 'Terminated', tone: '#8E5BC8', name: 'JBCL | Test promo codes 05.08', brand: '.jbcl', until: '09.09.2026' },
]

function JourneysList() {
  return (
    <ScreenFrame>
      <div className="flex">
        {/* Nav rail — Journey builder is where all of this happens. */}
        <nav
          className="shrink-0 w-[92px] py-3 flex flex-col gap-0.5"
          style={{ background: NAV_INK }}
          aria-hidden="true"
        >
          {NAV.map(item => {
            const active = item === 'Journey builder'
            return (
              <span
                key={item}
                className="px-2 py-2 text-center leading-tight"
                style={{
                  fontSize: '9.5px',
                  color: active ? PRODUCT_GREEN : 'rgba(255,255,255,.45)',
                  fontWeight: active ? 600 : 400,
                }}
              >
                {item}
              </span>
            )
          })}
        </nav>

        <div className="flex-1 min-w-0">
          <ScreenHeader title="Journeys" />
          <Tabs tabs={['Journeys', 'Drafts', 'Archived']} />

          <table className="w-full" style={{ fontSize: '11px' }}>
            <thead>
              <tr style={{ color: '#8A8F86' }}>
                <Th>Status</Th>
                <Th>Name</Th>
                <Th>Brand</Th>
                <Th>Entry until</Th>
              </tr>
            </thead>
            <tbody>
              {JOURNEY_ROWS.map(row => (
                <tr key={row.name} className="border-t" style={{ borderColor: '#EFF0ED' }}>
                  <Td>
                    <span className="inline-flex items-center gap-1.5" style={{ color: row.tone }}>
                      <span
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ background: row.tone }}
                      />
                      {row.status}
                    </span>
                  </Td>
                  <Td>
                    <span style={{ color: '#1F2328' }}>{row.name}</span>
                  </Td>
                  <Td>
                    <span
                      className="px-1.5 py-0.5 rounded"
                      style={{ background: '#F1F2EF', color: '#4A4F53' }}
                    >
                      {row.brand}
                    </span>
                  </Td>
                  <Td>
                    <span style={{ color: '#6E736B' }}>{row.until}</span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </ScreenFrame>
  )
}

// ─── Promo ───────────────────────────────────────────────────────────────────

/** The Create new menu. The two we actually use are marked. */
const PROMO_MENU: { label: string; used?: boolean }[] = [
  { label: 'Banner' },
  { label: 'Prediction', used: true },
  { label: 'Multi Number Prediction' },
  { label: 'Participation' },
  { label: 'Totalizator' },
  { label: 'Rating' },
  { label: 'Toss' },
  { label: 'Randomizer' },
  { label: 'Promo Page', used: true },
]

const PROMO_ROWS = [
  { name: 'Quest - Chile', mech: 'Banner', brand: '.jbcl' },
  { name: 'JBCL|SP|XSELLI', mech: 'Randomizer', brand: '.jbcl' },
  { name: 'JBCOM-Tourn 3ok -L', mech: 'Banner', brand: '.jbcom' },
]

function PromoList() {
  return (
    <ScreenFrame>
      {/* Tall enough that the whole Create new menu fits inside the card — the
          two marked items are the point of this screen and must not clip. */}
      <div className="relative min-h-[310px]">
        <ScreenHeader title="Promo" />
        <Tabs tabs={['Promo', 'Drafts']} />

        <table className="w-full" style={{ fontSize: '11px' }}>
          <thead>
            <tr style={{ color: '#8A8F86' }}>
              <Th>Status</Th>
              <Th>Name</Th>
              <Th>Mechanics</Th>
              <Th>Brand</Th>
            </tr>
          </thead>
          <tbody>
            {PROMO_ROWS.map(row => (
              <tr key={row.name} className="border-t" style={{ borderColor: '#EFF0ED' }}>
                <Td>
                  <span className="inline-flex items-center gap-1.5" style={{ color: PRODUCT_GREEN }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: PRODUCT_GREEN }} />
                    Active
                  </span>
                </Td>
                <Td>
                  <span style={{ color: '#1F2328' }}>{row.name}</span>
                </Td>
                <Td>
                  <span style={{ color: '#6E736B' }}>{row.mech}</span>
                </Td>
                <Td>
                  <span
                    className="px-1.5 py-0.5 rounded"
                    style={{ background: '#F1F2EF', color: '#4A4F53' }}
                  >
                    {row.brand}
                  </span>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* The open Create new menu, overlapping the table as it does for real. */}
        <div
          className="absolute right-3 top-11 w-[150px] rounded bg-white py-1 shadow-soft"
          style={{ border: '1px solid #E4E6E0' }}
        >
          {PROMO_MENU.map(item => (
            <div
              key={item.label}
              className={`px-3 py-1.5 leading-tight ${item.used ? 'rounded-md' : ''}`}
              style={{
                fontSize: '11px',
                color: item.used ? '#0E7A5A' : '#4A4F53',
                fontWeight: item.used ? 600 : 400,
                background: item.used ? '#E3F1EC' : undefined,
              }}
            >
              {item.label}
            </div>
          ))}
        </div>
      </div>
    </ScreenFrame>
  )
}

// ─── Shared chrome ───────────────────────────────────────────────────────────

function ScreenFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="surface-card mt-2 overflow-hidden select-none" aria-hidden="true">
      {children}
    </div>
  )
}

function ScreenHeader({ title }: { title: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-3">
      <span style={{ fontSize: '14px', fontWeight: 500, color: '#1F2328' }}>{title}</span>
      <span
        className="rounded px-3 py-1.5 text-white"
        style={{ background: PRODUCT_GREEN, fontSize: '11px', fontWeight: 500 }}
      >
        Create new
      </span>
    </div>
  )
}

function Tabs({ tabs }: { tabs: string[] }) {
  return (
    <div className="flex gap-6 px-4 border-b" style={{ borderColor: '#E4E6E0' }}>
      {tabs.map((t, i) => (
        <span
          key={t}
          className="pb-2"
          style={{
            fontSize: '11px',
            color: i === 0 ? '#1F2328' : '#9A9E96',
            borderBottom: i === 0 ? '2px solid #1F2328' : '2px solid transparent',
          }}
        >
          {t}
        </span>
      ))}
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="text-left font-normal px-4 pt-3 pb-2" style={{ fontSize: '10px' }}>
      {children}
    </th>
  )
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-2.5 align-middle">{children}</td>
}
