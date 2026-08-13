// ─── Journey builder palette ─────────────────────────────────────────────────
//
// The activity sidebar of the backoffice journey builder, category by category,
// in the order the real product lists them. Ids match the wire activity names
// where one exists, so an instruction can target `act-custom-segment` and mean
// the same node the composer would emit.
//
// Tints live here rather than in the glyphs: every icon paints in currentColor,
// so a category owns its colour and no icon has to know about it.

import type { ActivityIconKey } from '../components/icons/activityIcons'

export type ActivityCategoryId =
  | 'input-source'
  | 'flow-control'
  | 'communication'
  | 'delays'
  | 'connectors'
  | 'multiple-flows'
  | 'promotion-type'
  | 'conditions'
  | 'reward-type'

export interface ActivityCategory {
  id: ActivityCategoryId
  label: string
  /** Tailwind bg class for the tile. */
  tile: string
  /** Tailwind text class the glyph inherits through currentColor. */
  glyph: string
  /** Delays are the one category the product draws as circles. */
  shape: 'square' | 'circle'
}

export interface Activity {
  id: string
  label: string
  icon: ActivityIconKey
  category: ActivityCategoryId
}

export const ACTIVITY_CATEGORIES: ActivityCategory[] = [
  { id: 'input-source',    label: 'Input Source',    tile: 'bg-[#C8E0BC]', glyph: 'text-[#34693C]', shape: 'square' },
  { id: 'flow-control',    label: 'Flow control',    tile: 'bg-[#FDF4E3]', glyph: 'text-[#E2A93F]', shape: 'square' },
  { id: 'communication',   label: 'Communication',   tile: 'bg-[#E9F1F9]', glyph: 'text-[#6AA5DA]', shape: 'square' },
  { id: 'delays',          label: 'Delays',          tile: 'bg-[#F7F6C9]', glyph: 'text-[#C4BC45]', shape: 'circle' },
  { id: 'connectors',      label: 'Connectors',      tile: 'bg-[#FDEDE5]', glyph: 'text-[#F2946E]', shape: 'square' },
  { id: 'multiple-flows',  label: 'Multiple flows',  tile: 'bg-[#FDEBF4]', glyph: 'text-[#EA6BA3]', shape: 'square' },
  { id: 'promotion-type',  label: 'Promotion type',  tile: 'bg-[#E7F4ED]', glyph: 'text-[#56AE80]', shape: 'square' },
  { id: 'conditions',      label: 'Conditions',      tile: 'bg-[#F3EBF9]', glyph: 'text-[#A97BC8]', shape: 'square' },
  { id: 'reward-type',     label: 'Reward type',     tile: 'bg-[#EEEBF9]', glyph: 'text-[#8E80CC]', shape: 'square' },
]

export const ACTIVITIES: Activity[] = [
  // Input Source
  { id: 'act-custom-segment',      label: 'Custom Segment',     icon: 'customSegment',      category: 'input-source' },
  { id: 'act-reference-codes',     label: 'Reference codes',    icon: 'referenceCodes',     category: 'input-source' },
  { id: 'act-csv',                 label: 'CSV',                icon: 'csv',                category: 'input-source' },
  { id: 'act-api',                 label: 'API',                icon: 'api',                category: 'input-source' },
  { id: 'act-predefined-segment',  label: 'Predefined Segment', icon: 'predefinedSegment',  category: 'input-source' },
  { id: 'act-events',              label: 'Events',             icon: 'events',             category: 'input-source' },
  { id: 'act-promotion-source',    label: 'Promotion',          icon: 'promotionScreen',    category: 'input-source' },

  // Flow control
  { id: 'act-decision-split',      label: 'Decision split',                  icon: 'decisionSplit',   category: 'flow-control' },
  { id: 'act-random-split',        label: 'Random split',                    icon: 'randomSplit',     category: 'flow-control' },
  { id: 'act-sms-split',           label: 'Sms engagement split',            icon: 'smsSplit',        category: 'flow-control' },
  { id: 'act-email-split',         label: 'Email engagement split',          icon: 'emailSplit',      category: 'flow-control' },
  { id: 'act-native-push-split',   label: 'Native push engagement split',    icon: 'nativePushSplit', category: 'flow-control' },
  { id: 'act-onsite-split',        label: 'On-site messaging engagement split', icon: 'onsiteSplit',  category: 'flow-control' },

  // Communication
  { id: 'act-native-push',         label: 'Native push',        icon: 'nativePush',         category: 'communication' },
  { id: 'act-web-push',            label: 'Web push',           icon: 'webPush',            category: 'communication' },
  { id: 'act-sms',                 label: 'SMS',                icon: 'sms',                category: 'communication' },
  { id: 'act-email',               label: 'Email',              icon: 'email',              category: 'communication' },
  { id: 'act-onsite-messaging',    label: 'On-site messaging',  icon: 'onsiteMessaging',    category: 'communication' },
  { id: 'act-whatsapp',            label: 'WhatsApp',           icon: 'whatsapp',           category: 'communication' },

  // Delays
  { id: 'act-event-detector',      label: 'Event Detector',     icon: 'eventDetector',      category: 'delays' },
  { id: 'act-date',                label: 'Date',               icon: 'date',               category: 'delays' },
  { id: 'act-wait',                label: 'Wait',               icon: 'wait',               category: 'delays' },

  // Connectors
  { id: 'act-outgoing-api',        label: 'Outgoing API request', icon: 'outgoingApiRequest', category: 'connectors' },
  { id: 'act-campaign-connector',  label: 'Campaign Connector',   icon: 'campaignConnector',  category: 'connectors' },

  // Multiple flows
  { id: 'act-parallel-flows',      label: 'Parallel flows',     icon: 'parallelFlows',      category: 'multiple-flows' },
  { id: 'act-choosable-flows',     label: 'Choosable flows',    icon: 'choosableFlows',     category: 'multiple-flows' },

  // Promotion type
  { id: 'act-promotion',           label: 'Promotion',              icon: 'promotionScreen',        category: 'promotion-type' },
  { id: 'act-multipurpose-promo',  label: 'Multipurpose Promotion', icon: 'multipurposePromotion',  category: 'promotion-type' },

  // Conditions
  { id: 'act-deposit',             label: 'Deposit',             icon: 'deposit',             category: 'conditions' },
  { id: 'act-deposit-collection',  label: 'Deposit Collection',  icon: 'depositCollection',   category: 'conditions' },
  { id: 'act-bet-insurance',       label: 'Bet Insurance',       icon: 'betInsurance',        category: 'conditions' },
  { id: 'act-bet',                 label: 'Bet',                 icon: 'bet',                 category: 'conditions' },
  { id: 'act-bet-collection',      label: 'Bet Collection',      icon: 'betCollection',       category: 'conditions' },
  { id: 'act-casino-bet-collection', label: 'Casino Bet Collection', icon: 'casinoBetCollection', category: 'conditions' },

  // Reward type
  { id: 'act-sport-bonus',         label: 'Sport Bonus',        icon: 'sportBonus',         category: 'reward-type' },
  { id: 'act-casino-bonus',        label: 'Casino Bonus',       icon: 'casinoBonus',        category: 'reward-type' },
  { id: 'act-casino-freespin',     label: 'Casino FreeSpin',    icon: 'casinoFreeSpin',     category: 'reward-type' },
  { id: 'act-sport-freebet',       label: 'Sport FreeBet',      icon: 'sportFreeBet',       category: 'reward-type' },
  { id: 'act-money-bonus',         label: 'Money Bonus',        icon: 'moneyBonus',         category: 'reward-type' },
  { id: 'act-coins-bonus',         label: 'Coins Bonus',        icon: 'coinsBonus',         category: 'reward-type' },
]

export function activitiesIn(category: ActivityCategoryId): Activity[] {
  return ACTIVITIES.filter(a => a.category === category)
}

export function findActivity(id: string): Activity | undefined {
  return ACTIVITIES.find(a => a.id === id)
}
