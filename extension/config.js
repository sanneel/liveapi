// Shared constants + token helpers.
//
// Imported by background.js / popup.js / options.js (all ES modules).
// content.js CANNOT import this — MV3 content scripts are not modules — so the
// couple of values it needs are repeated there. Keep them in sync.

// The REA backoffice. Every generated script's BASE points here; the token we
// need is the bearer that this origin's own XHRs already carry.
export const BACKOFFICE_MATCH = 'https://*.rea-backoffice.gr8.tech/*';
export const BACKOFFICE_HOST_RE = /^https:\/\/[a-z0-9.-]+\.rea-backoffice\.gr8\.tech\//i;

// A token is only worth seeding if it still has this long to live. The scripts
// themselves refuse anything under 30s; be stricter, because a run that reserves
// JRN ids and then 401s halfway leaves orphan drafts behind.
export const MIN_TOKEN_TTL_S = 120;

// Where the CRM admin lives. Deployment-specific, so it is a setting; these are
// the local defaults. Options page requests the host permission for whatever the
// operator adds and registers the content script for it.
export const DEFAULT_CRM_ORIGINS = [
  'http://127.0.0.1:8000/*',
  'http://localhost:8000/*',
];

export const CONTENT_SCRIPT_ID = 'crm-run-button';

/** Decode a JWT payload without verifying it (we only read exp/typ). */
export function decodeJwt(token) {
  try {
    const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(part));
  } catch (e) {
    return null;
  }
}

/**
 * Mirror of usableAuth() in the generated scripts, plus a longer TTL floor.
 * Returns 'Bearer <jwt>' or null. Deliberately identical in its checks so the
 * extension never seeds a token the script itself would have rejected.
 */
export function usableAuth(value) {
  if (!value || !/^Bearer\s+\S+/i.test(value)) return null;
  const jwt = value.replace(/^Bearer\s+/i, '');
  const payload = decodeJwt(jwt);
  if (!payload || payload.typ !== 'Bearer') return null;
  if (!payload.exp || payload.exp - Date.now() / 1000 < MIN_TOKEN_TTL_S) return null;
  return 'Bearer ' + jwt;
}

/** Seconds of life left on 'Bearer <jwt>', or 0. */
export function tokenTtl(auth) {
  const payload = decodeJwt(String(auth || '').replace(/^Bearer\s+/i, ''));
  if (!payload || !payload.exp) return 0;
  return Math.max(0, Math.round(payload.exp - Date.now() / 1000));
}

// The one knob every generated script exposes. We replace this exact line so the
// operator never sees "Waiting for a token... click anything in the backoffice".
// Exact-match, single-occurrence only: see seedToken() in background.js.
export const MANUAL_TOKEN_LINE = "const MANUAL_TOKEN = '';";
