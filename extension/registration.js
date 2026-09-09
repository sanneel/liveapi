// Registering the CRM content script.
//
// Not declared in the manifest: the CRM hostname is deployment-specific
// (DEPLOY.md leaves it as your-domain.com), so the operator supplies it on the
// options page and Chrome prompts for the host permission. We register for
// exactly the granted set and nothing broader.

import { DEFAULT_CRM_ORIGINS, CONTENT_SCRIPT_ID } from './config.js';

export const ORIGINS_KEY = 'crmOrigins';

export async function getOrigins() {
  const got = await chrome.storage.local.get(ORIGINS_KEY);
  return got[ORIGINS_KEY] || DEFAULT_CRM_ORIGINS;
}

export async function grantedOrigins() {
  const out = [];
  for (const match of await getOrigins()) {
    if (await chrome.permissions.contains({ origins: [match] })) out.push(match);
  }
  return out;
}

/**
 * Unregister then register, so an origin the operator removed really stops
 * being injected. Returns the origins now covered.
 */
export async function syncRegistration() {
  const granted = await grantedOrigins();

  const existing = await chrome.scripting
    .getRegisteredContentScripts({ ids: [CONTENT_SCRIPT_ID] })
    .catch(() => []);
  if (existing.length) {
    await chrome.scripting.unregisterContentScripts({ ids: [CONTENT_SCRIPT_ID] });
  }
  if (!granted.length) return granted;

  await chrome.scripting.registerContentScripts([{
    id: CONTENT_SCRIPT_ID,
    matches: granted,
    js: ['content.js'],
    css: ['content.css'],
    runAt: 'document_idle',
    persistAcrossSessions: true,
  }]);
  return granted;
}
