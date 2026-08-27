// ─── Brands and the journey naming convention ────────────────────────────────
//
// The backoffice tags every journey with a brand code (.jbcl, .pmcl, .jbcom).
// The team's convention is that the journey NAME repeats that code, so a list
// of 1,800 journeys can be scanned by brand without opening anything:
//
//     JBCL | Torneo Suerte Loca 06.08
//     PMCL | Regular Weekend SP Promotion 19.05
//
// The rule is enforced here rather than by matching one hard-coded string, so
// the trainee learns the shape and can name a journey anything within it.

export interface Brand {
  /** Select value and the code that must open the journey name. */
  code: string
}

export const BRANDS: Brand[] = [{ code: 'JBCL' }, { code: 'PMCL' }, { code: 'JBCOM' }]

export const BRAND_OPTIONS = BRANDS.map(b => ({ value: b.code, label: b.code }))

/** `CODE | some name 06.08` — code, pipe, a name, then a dd.mm date. */
export function journeyNameMatchesConvention(value: string, brandCode: string | undefined): boolean {
  if (!brandCode) return false
  const escaped = brandCode.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^${escaped} \\| .+\\d{2}\\.\\d{2}`).test(value.trim())
}

/** Shown in the hint so the trainee has a concrete shape to copy. */
export function journeyNameExample(brandCode: string | undefined): string {
  return `${brandCode ?? 'JBCL'} | Welcome Casino 06.08`
}
