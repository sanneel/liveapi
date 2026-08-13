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
    case 'journey-log':
      return <JourneyLog />
    case 'randomizer-players':
      return <RandomizerPlayers />
    case 'player-bonus-card':
      return <PlayerBonusCard />
  }
}

// ─── One real spin, three screens ────────────────────────────────────────────
//
// Captured 07.08.2026 from randomizer RND-0-17731 (JBCL|CS|WOF|07.08.26) and the
// journey it feeds, JRN-0-572381. Reproduced rather than screenshotted so the
// account number can be truncated and the type stays legible at any width.

const LOG_ROWS = [
  {
    time: '08:12:11',
    name: 'Deposit',
    flow: 'Flow 1',
    event: 'Activated',
    detail: ['Deposit condition status: Active', 'Expired at: 08.08.2026 08:12:10'],
  },
  {
    time: '08:12:10',
    name: '15k dep',
    kind: 'Promotion',
    flow: 'Flow 1',
    event: 'Accepted',
    detail: ['Promotion status: Accepted', 'Display ID: 672078'],
  },
  {
    time: '08:12:10',
    name: 'Multipurpose Promotion',
    event: 'Accepted',
    detail: ['Promotion status: Accepted', 'Promotion Currency: CLP'],
  },
  {
    time: '08:10:23',
    name: 'Multipurpose Promotion',
    event: 'Offered',
    detail: ['Promotion offer expired at: 08.08.2026 08:10:22', 'Promotion status: Offered'],
  },
  { time: '08:10:22', name: 'Decision split', event: 'Other', detail: [] },
  {
    time: '08:10:07',
    name: 'API',
    event: 'Player added to journey',
    detail: ['Player currency: CLP', 'Added by system'],
  },
]

function JourneyLog() {
  return (
    <ScreenFrame>
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#E4E6E0' }}>
        <span style={{ fontSize: '12.5px', fontWeight: 500, color: '#1F2328' }}>
          Player Details <span style={{ color: '#6B7280' }}>jbcl4660…8434</span>
        </span>
        <span
          className="rounded-full px-2 py-0.5"
          style={{ background: '#E7F4ED', color: PRODUCT_GREEN, fontSize: '10px', fontWeight: 600 }}
        >
          ● Active
        </span>
      </div>
      <Tabs tabs={['Journey log', 'Journey data', 'Journey flow', 'Exit criteria']} />
      <table className="w-full" style={{ fontSize: '10.5px' }}>
        <thead>
          <tr style={{ color: '#8A8F86' }}>
            <Th>Event date</Th>
            <Th>Activity name</Th>
            <Th>Event</Th>
            <Th>Event details</Th>
          </tr>
        </thead>
        <tbody>
          {LOG_ROWS.map((r, i) => (
            <tr key={i} style={{ background: i % 2 ? '#FAFAF8' : undefined }}>
              <Td>
                <span style={{ color: '#6B7280' }}>07.08.2026</span>
                <br />
                <span style={{ fontWeight: 600, color: '#1F2328' }}>{r.time}</span>
              </Td>
              <Td>
                <span style={{ color: '#1F2328', fontWeight: 500 }}>{r.name}</span>
                {r.flow && (
                  <span
                    className="ml-1.5 rounded px-1 py-0.5"
                    style={{ background: '#EDEEEA', color: '#4B5563', fontSize: '9px', fontWeight: 600 }}
                  >
                    {r.flow}
                  </span>
                )}
                {r.kind && (
                  <>
                    <br />
                    <span style={{ color: '#9A9E96', fontSize: '9.5px' }}>{r.kind}</span>
                  </>
                )}
              </Td>
              <Td>
                <span style={{ color: '#1F2328' }}>{r.event}</span>
              </Td>
              <Td>
                {r.detail.map(d => (
                  <span key={d} style={{ color: '#6B7280', display: 'block', lineHeight: 1.5 }}>
                    {d}
                  </span>
                ))}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScreenFrame>
  )
}

function RandomizerPlayers() {
  const meta = [
    ['Published at', '07 Aug 2026 08:01'],
    ['Start date', '07 Aug 2026 08:02'],
    ['End date', '08 Aug 2026 07:58'],
    ['Use in journeys', 'No'],
  ]
  return (
    <ScreenFrame>
      <div className="flex">
        <div
          className="shrink-0 w-[150px] border-r px-3 py-3 flex flex-col gap-2.5"
          style={{ borderColor: '#E4E6E0', background: '#FAFAF8' }}
        >
          <span style={{ color: PRODUCT_GREEN, fontSize: '10px', fontWeight: 600 }}>● Active</span>
          <div>
            <span style={{ fontSize: '10.5px', fontWeight: 600, color: '#1F2328' }}>
              Randomizer: RND-0-17731
            </span>
            <br />
            <span style={{ fontSize: '10px', color: '#6B7280' }}>JBCL|CS|WOF|07.08.26</span>
          </div>
          <div>
            <span style={{ fontSize: '9px', color: '#8A8F86' }}>URL</span>
            <div
              className="mt-0.5 rounded border px-1.5 py-1 truncate"
              style={{ borderColor: '#E4E6E0', background: '#fff', fontSize: '9px', color: '#4B5563' }}
            >
              jugabet.cl/services/promo…
            </div>
          </div>
          {meta.map(([k, v]) => (
            <div key={k}>
              <span style={{ fontSize: '9px', color: '#8A8F86' }}>{k}</span>
              <br />
              <span style={{ fontSize: '10px', color: '#1F2328' }}>{v}</span>
            </div>
          ))}
        </div>

        <div className="flex-1 min-w-0">
          <ScreenHeader title="Players list" />
          <Tabs tabs={['All players']} />
          <table className="w-full" style={{ fontSize: '10.5px' }}>
            <thead>
              <tr style={{ color: '#8A8F86' }}>
                <Th>Account</Th>
                <Th>Claimed at</Th>
                <Th>Bonus campaign</Th>
                <Th>Description</Th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ background: '#FAFAF8' }}>
                <Td>
                  <span style={{ color: '#1F2328' }}>jbcl4660…8434</span>
                </Td>
                <Td>
                  <span style={{ color: '#6B7280' }}>07.08.2026</span>
                  <br />
                  <span style={{ fontWeight: 600, color: '#1F2328' }}>16:10</span>
                </Td>
                <Td>
                  <span style={{ fontWeight: 600, color: '#1F2328' }}>JRN-0-572381</span>
                </Td>
                <Td>
                  <span style={{ color: '#6B7280' }}>Wheel of fortune | 50FS to dep</span>
                </Td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </ScreenFrame>
  )
}

// The player-facing screens are the app's own dark navy, not backoffice white.
const SITE_INK = '#1C2951'
const SITE_CARD = '#141F3D'
const SITE_LIME = '#C4EE2B'

function PlayerBonusCard() {
  return (
    <ScreenFrame>
      <div className="px-4 py-4" style={{ background: SITE_INK }}>
        <p className="text-center" style={{ color: '#fff', fontSize: '12px', fontWeight: 600 }}>
          Promoción
        </p>
        <div className="mt-3 rounded-xl px-3 py-3" style={{ background: SITE_CARD }}>
          <p style={{ color: '#fff', fontSize: '11.5px', fontWeight: 700 }}>Bonificaciones</p>
          <p className="mt-2" style={{ color: 'rgba(255,255,255,.55)', fontSize: '9.5px' }}>
            ACTIVA · 1
          </p>
          <div
            className="mt-2 rounded-lg overflow-hidden"
            style={{ background: '#0F1830', border: '1px solid rgba(255,255,255,.08)' }}
          >
            <div className="px-3 pt-3 pb-2 flex items-start gap-2">
              <span
                className="rounded px-1.5 py-0.5"
                style={{ background: '#E879C6', color: '#2A0A20', fontSize: '8.5px', fontWeight: 700 }}
              >
                CASINO
              </span>
              <span style={{ color: SITE_LIME, fontSize: '8.5px', fontWeight: 700 }}>
                ⏱ 23H 59M RESTANTES
              </span>
            </div>
            <p className="px-3 pb-3" style={{ color: '#fff', fontSize: '13px', fontWeight: 700, lineHeight: 1.25 }}>
              50 Giros Gratis | Apuesta $200
            </p>
            <div
              className="px-3 py-2.5 flex items-center justify-between"
              style={{ borderTop: '1px solid rgba(255,255,255,.08)' }}
            >
              <span>
                <span style={{ color: '#fff', fontSize: '12px', fontWeight: 700 }}>15000 CLP</span>
                <br />
                <span style={{ color: 'rgba(255,255,255,.5)', fontSize: '9px' }}>Depósito mínimo</span>
              </span>
              <span
                className="rounded-full px-3 py-1.5"
                style={{ background: SITE_LIME, color: '#16210A', fontSize: '10px', fontWeight: 700 }}
              >
                Depósito
              </span>
            </div>
          </div>
        </div>
      </div>
    </ScreenFrame>
  )
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
