// ─── Journey activity glyphs ─────────────────────────────────────────────────
//
// One line-drawn glyph per activity in the backoffice journey palette, traced
// from the real sidebar. Every glyph paints in `currentColor` so the tile
// decides the tint (see journeyActivities.ts) — never hard-code a colour here.
//
// All glyphs share a 24×24 box, 1.7 stroke, round caps. Keep new ones on that
// grid or they will not sit level with their neighbours in the palette.

import type { SVGProps, ReactNode } from 'react'

function Glyph({ children, ...rest }: SVGProps<SVGSVGElement> & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

/** The `← →` pair every "engagement split" glyph carries under its subject. */
const SplitArrows = () => (
  <>
    <path d="M2.4 20h5.4M4.6 17.9 2.4 20l2.2 2.1" />
    <path d="M21.6 20h-5.4M19.4 17.9 21.6 20l-2.2 2.1" />
  </>
)

/**
 * Head-and-shoulders used by every Input Source glyph. Fixed geometry, spanning
 * x 2.4→11.6 — every secondary glyph in those tiles starts at x ≥ 13 so the two
 * never touch.
 */
const Person = () => (
  <>
    <circle cx="7" cy="6.8" r="2.9" />
    <path d="M2.4 17.6c0-2.9 2.1-4.8 4.6-4.8s4.6 1.9 4.6 4.8" />
  </>
)

/** Counter-clockwise "collection" arc that wraps the Bet/Deposit collectors. */
const CollectionArc = () => (
  <>
    <path d="M3.4 12a8.6 8.6 0 1 0 2.6-6.1" />
    <path d="M2.8 3v4.3h4.3" />
  </>
)

// ─── Input Source ────────────────────────────────────────────────────────────

const CustomSegment = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <Person />
    <ellipse cx="17.6" cy="11.4" rx="3.7" ry="1.6" />
    <path d="M13.9 11.4v6.6c0 .9 1.7 1.6 3.7 1.6s3.7-.7 3.7-1.6v-6.6" />
    <path d="M13.9 14.7c0 .9 1.7 1.6 3.7 1.6s3.7-.7 3.7-1.6" />
  </Glyph>
)

const ReferenceCodes = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <Person />
    <path d="m14.4 16.4 2.4 2.4 4.8-4.8" />
  </Glyph>
)

const CsvSource = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <Person />
    <path d="M14.6 8.4h3.2l3.2 3.2v7.6a1.2 1.2 0 0 1-1.2 1.2h-5.2a1.2 1.2 0 0 1-1.2-1.2V9.6a1.2 1.2 0 0 1 1.2-1.2Z" />
    <path d="M17.8 8.4v3.2h3.2" />
    <path d="M15.8 15.2h3.6M15.8 17.6h2.4" />
  </Glyph>
)

const ApiSource = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <Person />
    <path d="m17.4 8.6 4.1 2.1v4.6l-4.1 2.1-4.1-2.1v-4.6Z" />
    <path d="m13.3 10.7 4.1 2.1 4.1-2.1M17.4 12.8v4.6" />
  </Glyph>
)

const PredefinedSegment = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <Person />
    <circle cx="17.6" cy="15.6" r="2.3" />
    <path d="M17.6 11.5v1.3M17.6 18.4v1.3M13.5 15.6h1.3M20.4 15.6h1.3M14.7 12.7l.9.9M19.6 17.6l.9.9M20.5 12.7l-.9.9M14.7 18.5l.9-.9" />
  </Glyph>
)

const Events = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="3.2" y="3.6" width="17.6" height="16.8" rx="3.2" />
    <path d="m7 9.4 1.4 1.4L11 8.2" />
    <path d="M13.6 9.6h3.6" />
    <path d="m7 15.6 1.4 1.4L11 14.4" />
    <path d="M13.6 15.8h3.6" />
  </Glyph>
)

/** Monitor + phone carrying a star — used by both "Promotion" tiles. */
const PromotionScreen = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="1.6" y="4.2" width="14" height="10.2" rx="1.7" />
    <path d="M5.8 18.4h5.6M8.6 14.4v4" />
    <path d="m8.6 6.3 1.35 2.74 3.02.44-2.19 2.13.52 3.01-2.7-1.42-2.7 1.42.52-3.01-2.19-2.13 3.02-.44z" />
    <rect x="17.2" y="8.4" width="5.2" height="11.2" rx="1.5" />
    <path d="M19.1 10.4h1.4" />
  </Glyph>
)

// ─── Flow control ────────────────────────────────────────────────────────────

const DecisionSplit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M12 2.8v18.4M2.8 12h18.4" />
    <path d="M9.4 5.4 12 2.8l2.6 2.6M9.4 18.6 12 21.2l2.6-2.6M5.4 9.4 2.8 12l2.6 2.6M18.6 9.4 21.2 12l-2.6 2.6" />
  </Glyph>
)

const RandomSplit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="6" cy="6.6" r="2.5" />
    <path d="M2.2 14c0-2.1 1.7-3.6 3.8-3.6s3.8 1.5 3.8 3.6" />
    <circle cx="18" cy="6.6" r="2.5" />
    <path d="M14.2 14c0-2.1 1.7-3.6 3.8-3.6s3.8 1.5 3.8 3.6" />
    <SplitArrows />
  </Glyph>
)

const SmsSplit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M3.6 3.6h16.8c.9 0 1.6.7 1.6 1.6v6.4c0 .9-.7 1.6-1.6 1.6H9.2l-3.8 2.8V13.2H3.6c-.9 0-1.6-.7-1.6-1.6V5.2c0-.9.7-1.6 1.6-1.6Z" />
    <SplitArrows />
  </Glyph>
)

const EmailSplit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.2" y="4" width="19.6" height="11.4" rx="1.8" />
    <path d="m2.2 6.1 9.8 6.2 9.8-6.2" />
    <SplitArrows />
  </Glyph>
)

const NativePushSplit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="7.8" y="2" width="8.4" height="14" rx="1.9" />
    <path d="M10.7 4.4h2.6" />
    <SplitArrows />
  </Glyph>
)

const OnsiteSplit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.2" y="4" width="19.6" height="11.4" rx="1.8" />
    <path d="M5.4 8h6.4M5.4 11.4h4.4" />
    <circle cx="17.4" cy="8.6" r="1.7" />
    <SplitArrows />
  </Glyph>
)

// ─── Communication ───────────────────────────────────────────────────────────

const NativePush = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="6.4" y="1.8" width="11.2" height="20.4" rx="2.4" />
    <path d="M10.4 4.6h3.2M10.4 19.6h3.2" />
  </Glyph>
)

const WebPush = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="1.8" y="4.6" width="14.4" height="10.2" rx="1.7" />
    <path d="M6.2 18.6h5.6M9 14.8v3.8" />
    <rect x="17.4" y="9" width="4.8" height="10.6" rx="1.4" />
    <path d="M19.2 11h1.2" />
  </Glyph>
)

const Sms = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M4 4h16c1.1 0 2 .9 2 2v8c0 1.1-.9 2-2 2h-8.6L6 20.6V16H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2Z" />
  </Glyph>
)

const Email = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2" y="4.8" width="20" height="14.4" rx="2.1" />
    <path d="m2 7.4 10 6.6 10-6.6" />
  </Glyph>
)

const OnsiteMessaging = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.2" y="4.8" width="19.6" height="14.4" rx="2.1" />
    <rect x="5.2" y="8.2" width="5" height="4.2" rx="1.1" />
    <path d="M12.6 8.8h6.2M12.6 11.8h4.6M5.2 15.8h13.6" />
  </Glyph>
)

const WhatsApp = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M12 2.4c-5.3 0-9.6 4.2-9.6 9.3 0 1.8.5 3.4 1.4 4.8l-1.4 5.1 5.3-1.4c1.3.7 2.8 1.1 4.3 1.1 5.3 0 9.6-4.2 9.6-9.3S17.3 2.4 12 2.4Z" />
    <path d="M9.1 8.1c.3-.1.7 0 .9.3l.8 1.4c.1.2.1.5 0 .7l-.5.7c-.1.2-.1.4 0 .6.5.9 1.3 1.6 2.3 2.1.2.1.5 0 .6-.1l.6-.6c.2-.2.5-.2.7-.1l1.5.7c.3.2.4.5.3.8-.3.9-1.2 1.4-2.1 1.3-2.9-.3-5.3-2.6-5.7-5.5-.1-.9.3-1.7 1-2Z" />
  </Glyph>
)

// ─── Delays ──────────────────────────────────────────────────────────────────

const EventDetector = Events

const DateGlyph = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.8" y="4.6" width="18.4" height="16.6" rx="2.6" />
    <path d="M2.8 9.4h18.4M8 2.6v4M16 2.6v4" />
    <circle cx="8.2" cy="13.4" r=".95" fill="currentColor" stroke="none" />
    <circle cx="12" cy="13.4" r=".95" fill="currentColor" stroke="none" />
    <circle cx="15.8" cy="13.4" r=".95" fill="currentColor" stroke="none" />
    <circle cx="8.2" cy="17.2" r=".95" fill="currentColor" stroke="none" />
    <circle cx="12" cy="17.2" r=".95" fill="currentColor" stroke="none" />
  </Glyph>
)

const Wait = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M6.4 2.6h11.2M6.4 21.4h11.2" />
    <path d="M8 2.6v3.7c0 1.5 4 4.3 4 5.7 0-1.4 4-4.2 4-5.7V2.6" />
    <path d="M8 21.4v-3.7c0-1.5 4-4.3 4-5.7 0 1.4 4 4.2 4 5.7v3.7" />
  </Glyph>
)

// ─── Connectors ──────────────────────────────────────────────────────────────

const OutgoingApiRequest = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="12" cy="4.4" r="2.5" />
    <circle cx="5.2" cy="18.4" r="2.5" />
    <circle cx="18.8" cy="18.4" r="2.5" />
    <path d="M10.2 6.2 6.6 16.1" />
    <path d="M13.8 6.2l3.6 9.9" />
    <path d="M7.7 18.4h8.6" />
  </Glyph>
)

/** Two hooks joined by a bar — "link one campaign to another". */
const CampaignConnector = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M10.2 7.4H7.6a4.6 4.6 0 0 0 0 9.2h2.6" />
    <path d="M13.8 16.6h2.6a4.6 4.6 0 0 0 0-9.2h-2.6" />
    <path d="M8.8 12h6.4" />
  </Glyph>
)

// ─── Multiple flows ──────────────────────────────────────────────────────────

const ParallelFlows = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="M8.4 3.4v16.8M5.5 17.3l2.9 2.9 2.9-2.9" />
    <path d="M15.6 3.4v16.8M12.7 17.3l2.9 2.9 2.9-2.9" />
  </Glyph>
)

/** One root fanning out to three choices. */
const ChoosableFlows = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="4.6" cy="12" r="2.2" />
    <circle cx="19.2" cy="5.2" r="2.2" />
    <circle cx="19.2" cy="12" r="2.2" />
    <circle cx="19.2" cy="18.8" r="2.2" />
    <path d="M6.8 12h10.2" />
    <path d="M6.4 10.8c1.7-.6 2.2-1.9 3.2-3.3 1-1.4 2.4-2.3 7.2-2.3" />
    <path d="M6.4 13.2c1.7.6 2.2 1.9 3.2 3.3 1 1.4 2.4 2.3 7.2 2.3" />
  </Glyph>
)

// ─── Promotion type ──────────────────────────────────────────────────────────

const MultipurposePromotion = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="3.4" y="2.8" width="17.2" height="18.4" rx="2.6" />
    <path d="m12 7.6 1.5 3.1 3.4.5-2.5 2.4.6 3.4-3-1.6-3 1.6.6-3.4-2.5-2.4 3.4-.5Z" />
  </Glyph>
)

// ─── Conditions ──────────────────────────────────────────────────────────────

/**
 * The dollar stroke, centred on (12,12) at full size. To shrink it — e.g. to sit
 * inside a collection arc — wrap it in a scaling <g> and raise strokeWidth by the
 * inverse factor, so the line keeps the 1.7 weight of every other glyph.
 */
const Dollar = () => (
  <>
    <path d="M12 6.6v10.8" />
    <path d="M14.8 9.2c-.5-.9-1.5-1.4-2.8-1.4-1.7 0-2.9.9-2.9 2.2 0 1.4 1.2 1.9 2.9 2.2 1.7.3 2.9.8 2.9 2.2 0 1.3-1.2 2.2-2.9 2.2-1.4 0-2.4-.5-2.9-1.5" />
  </>
)

const Deposit = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="12" cy="12" r="9.2" />
    <Dollar />
  </Glyph>
)

const DepositCollection = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <CollectionArc />
    {/* 0.62 scale about (12,12.6); strokeWidth 1.7/0.62 keeps the line weight. */}
    <g transform="translate(12 12.6) scale(0.62) translate(-12 -12)" strokeWidth={2.74}>
      <Dollar />
    </g>
  </Glyph>
)

const BetInsurance = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <path d="m12 2.4 7.8 3.1v6.2c0 4.6-3.1 8.3-7.8 10.3-4.7-2-7.8-5.7-7.8-10.3V5.5Z" />
    <rect x="8" y="9" width="8" height="5.4" rx="1.2" />
    <path d="M12 9v5.4" strokeDasharray="1.4 1.4" />
  </Glyph>
)

const Bet = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.4" y="6" width="19.2" height="12" rx="2.2" />
    <path d="M12 7v10" strokeDasharray="2.2 2.2" />
  </Glyph>
)

const BetCollection = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <CollectionArc />
    <rect x="8.2" y="9.8" width="7.6" height="5" rx="1.2" />
    <path d="M12 9.8v5" strokeDasharray="1.3 1.3" />
  </Glyph>
)

const CasinoBetCollection = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <CollectionArc />
    <circle cx="12" cy="12.4" r="4.2" />
    <path d="M12 8.2v1.7M12 14.9v1.7M7.8 12.4h1.7M14.5 12.4h1.7" />
  </Glyph>
)

// ─── Reward type ─────────────────────────────────────────────────────────────

/** Football: centre pentagon with five seams running to the edge. */
const SportBonus = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="12" cy="12" r="9.2" />
    <path d="m12 6.6 4.2 3-1.6 5H9.4l-1.6-5Z" />
    <path d="M12 6.6V3.1M16.2 9.6l3.3-1.2M14.6 14.6l2.1 2.9M9.4 14.6l-2.1 2.9M7.8 9.6 4.5 8.4" />
  </Glyph>
)

/**
 * A casino chip: ring plus four edge notches. Deliberately has no spokes — with
 * them it reads as a wheel and stops being distinguishable from Sport Bonus.
 */
const CasinoBonus = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="12" cy="12" r="9.2" />
    <circle cx="12" cy="12" r="4.6" />
    <path d="M12 2.8v3.7M12 17.5v3.7M2.8 12h3.7M17.5 12h3.7" />
  </Glyph>
)

const CasinoFreeSpin = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.8" y="3.2" width="18.4" height="17.6" rx="3.2" />
    <text
      x="9.6"
      y="17.2"
      fontSize="11.5"
      fontWeight="700"
      fontFamily="Inter, system-ui, sans-serif"
      textAnchor="middle"
      fill="currentColor"
      stroke="none"
    >
      7
    </text>
    <path d="M15.4 8.4a4.4 4.4 0 0 1 0 7.2" />
  </Glyph>
)

const SportFreeBet = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="2.2" y="6" width="19.6" height="12" rx="2.2" />
    <text
      x="12"
      y="14.4"
      fontSize="5.6"
      fontWeight="700"
      letterSpacing="0.2"
      fontFamily="Inter, system-ui, sans-serif"
      textAnchor="middle"
      fill="currentColor"
      stroke="none"
    >
      FREE
    </text>
  </Glyph>
)

const MoneyBonus = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <rect x="1.8" y="4.4" width="14.4" height="10.4" rx="2" />
    <path d="M1.8 8.2h14.4" />
    <path d="M5 11.6h3" />
    <path d="M18.6 14.4v7.2M15 18h7.2" />
  </Glyph>
)

const CoinsBonus = (p: SVGProps<SVGSVGElement>) => (
  <Glyph {...p}>
    <circle cx="12" cy="12" r="9.2" />
    <path d="M15.1 9.3a4.1 4.1 0 1 0 0 5.4" />
  </Glyph>
)

// ─── Registry ────────────────────────────────────────────────────────────────

export const ACTIVITY_ICONS = {
  // Input Source
  customSegment: CustomSegment,
  referenceCodes: ReferenceCodes,
  csv: CsvSource,
  api: ApiSource,
  predefinedSegment: PredefinedSegment,
  events: Events,
  promotionScreen: PromotionScreen,
  // Flow control
  decisionSplit: DecisionSplit,
  randomSplit: RandomSplit,
  smsSplit: SmsSplit,
  emailSplit: EmailSplit,
  nativePushSplit: NativePushSplit,
  onsiteSplit: OnsiteSplit,
  // Communication
  nativePush: NativePush,
  webPush: WebPush,
  sms: Sms,
  email: Email,
  onsiteMessaging: OnsiteMessaging,
  whatsapp: WhatsApp,
  // Delays
  eventDetector: EventDetector,
  date: DateGlyph,
  wait: Wait,
  // Connectors
  outgoingApiRequest: OutgoingApiRequest,
  campaignConnector: CampaignConnector,
  // Multiple flows
  parallelFlows: ParallelFlows,
  choosableFlows: ChoosableFlows,
  // Promotion type
  multipurposePromotion: MultipurposePromotion,
  // Conditions
  deposit: Deposit,
  depositCollection: DepositCollection,
  betInsurance: BetInsurance,
  bet: Bet,
  betCollection: BetCollection,
  casinoBetCollection: CasinoBetCollection,
  // Reward type
  sportBonus: SportBonus,
  casinoBonus: CasinoBonus,
  casinoFreeSpin: CasinoFreeSpin,
  sportFreeBet: SportFreeBet,
  moneyBonus: MoneyBonus,
  coinsBonus: CoinsBonus,
} as const

export type ActivityIconKey = keyof typeof ACTIVITY_ICONS

export function ActivityIcon({
  name,
  className = 'w-6 h-6',
}: {
  name: ActivityIconKey
  className?: string
}) {
  const Component = ACTIVITY_ICONS[name]
  return <Component className={className} />
}
