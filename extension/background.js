// Service worker: capture the backoffice token, hold the run queue, drive runs.
//
// WHY chrome.debugger AND NOT scripting.executeScript
// --------------------------------------------------
// The generated scripts are pure API clients (fetch + a bearer header) but they
// are written to run *as the page*: 48 of the 54 in console_scripts/ capture the
// token by monkeypatching window.fetch, and all 54 send credentials:'include'.
// Reproduce that faithfully or don't reproduce it at all:
//
//   * An ISOLATED-world content script cannot patch the page's window.fetch.
//   * MAIN-world injection of a *dynamic string* needs eval, which the page CSP
//     may forbid — and we would only find out in production.
//   * Fetching from an extension page makes the requests third-party, so a
//     SameSite session cookie would silently stop being sent.
//
// Runtime.evaluate is what the DevTools console does. Same context, same
// cookies, same semantics as the paste it replaces — and
// allowUnsafeEvalBlockedByCSP settles the CSP question outright. The cost is
// Chrome's "started debugging this browser" bar, which goes away on detach.
//
// It also means a script runs byte-for-byte as generated, with exactly one
// exception: the MANUAL_TOKEN line (see seedToken).

import {
  BACKOFFICE_MATCH,
  MANUAL_TOKEN_LINE,
  usableAuth,
  tokenTtl,
} from './config.js';
import { syncRegistration } from './registration.js';
import { formatConsoleArgs } from './console_format.js';

// registerContentScripts persists, but an update or a revoked permission can
// leave it stale. Re-derive it from what we actually hold.
chrome.runtime.onInstalled.addListener(() => syncRegistration().catch(() => {}));
chrome.runtime.onStartup.addListener(() => syncRegistration().catch(() => {}));
chrome.permissions.onAdded.addListener(() => syncRegistration().catch(() => {}));
chrome.permissions.onRemoved.addListener(() => syncRegistration().catch(() => {}));

// ── persistence ───────────────────────────────────────────────────────────
// Everything lives in chrome.storage.session, not module scope: an MV3 worker
// is torn down after ~30s idle, and "clicked Run in the CRM, opened the popup a
// minute later, queue was empty" is exactly the papercut this extension exists
// to remove. session (not local) because a queued job is a rendered draft
// payload — it belongs in memory for this browser session, never on disk.

const TOKEN_KEY = 'auth';
const QUEUE_KEY = 'queue';
const ACTIVE_KEY = 'active';

// One run at a time, on purpose: these scripts reserve JRN ids and POST drafts,
// and two concurrent runs are how you get "activities with the same identifier
// already exist".
const MAX_QUEUE = 5;
const MAX_LINES = 2000;
// storage.session gives us 10 MB. gow_combined is ~650 KB, so this is roomy,
// but refuse loudly rather than blow the quota mid-write.
const MAX_TOTAL_BYTES = 6 * 1024 * 1024;

const read = async (key, fallback) => {
  const got = await chrome.storage.session.get(key);
  return key in got && got[key] != null ? got[key] : fallback;
};
const write = (key, value) => chrome.storage.session.set({ [key]: value });

const getQueue = () => read(QUEUE_KEY, []);
const getActive = () => read(ACTIVE_KEY, null);

// ── token capture ─────────────────────────────────────────────────────────
// Passive: read the Authorization header off the backoffice's own traffic. No
// page injection, nothing to break. This is the piece an extension can do that
// a pasted script cannot, and it is why the "click anything in the backoffice
// UI so the page makes a request" step disappears.

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const header = (details.requestHeaders || []).find(
      (h) => h.name.toLowerCase() === 'authorization',
    );
    if (!header) return;
    const auth = usableAuth(header.value || '');
    if (auth) write(TOKEN_KEY, auth);
  },
  { urls: [BACKOFFICE_MATCH] },
  ['requestHeaders'],
);

async function currentToken() {
  // Re-validate on read: the worker may have slept past the token's expiry.
  return usableAuth(await read(TOKEN_KEY, ''));
}

// ── state for the popup ───────────────────────────────────────────────────

async function snapshot() {
  const [queue, active, auth] = await Promise.all([getQueue(), getActive(), currentToken()]);
  return {
    queue: queue.map(({ id, name, source, receivedAt, code }) => ({
      id, name, source, receivedAt, bytes: code.length,
    })),
    active,
    token: { present: !!auth, ttl: auth ? tokenTtl(auth) : 0 },
  };
}

async function broadcast() {
  // The popup is usually closed; a failed send is expected, not an error.
  chrome.runtime.sendMessage({ type: 'STATE', state: await snapshot() }).catch(() => {});
}

// ── run log ───────────────────────────────────────────────────────────────

async function log(level, text) {
  const active = await getActive();
  if (!active) return;
  active.lines.push({ level, text, at: Date.now() });
  if (active.lines.length > MAX_LINES) {
    active.lines.splice(0, active.lines.length - MAX_LINES);
  }
  // Journey ids are the thing the operator actually needs out of a run, and they
  // only ever appear in the log. Surface them separately.
  for (const m of text.matchAll(/\bJRN-[A-Za-z0-9-]+/g)) {
    if (!active.journeyIds.includes(m[0])) active.journeyIds.push(m[0]);
  }
  await write(ACTIVE_KEY, active);
  await broadcast();
}

// ── intake ────────────────────────────────────────────────────────────────

async function enqueue(incoming) {
  const code = incoming && incoming.code;
  if (typeof code !== 'string' || !code.trim()) throw new Error('Empty script.');

  const job = {
    id: crypto.randomUUID(),
    name: String((incoming && incoming.name) || 'console script').slice(0, 200),
    source: String((incoming && incoming.source) || 'unknown').slice(0, 300),
    code,
    receivedAt: Date.now(),
  };

  let queue = await getQueue();
  // Re-clicking Run in the CRM should replace the pending copy of the same
  // script, not stack a second identical run behind it.
  queue = queue.filter((j) => j.name !== job.name);
  queue.push(job);
  if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);

  const bytes = queue.reduce((n, j) => n + j.code.length, 0);
  if (bytes > MAX_TOTAL_BYTES) {
    throw new Error(
      `Queue would hold ${(bytes / 1048576).toFixed(1)} MB. Run or discard what is already queued first.`,
    );
  }

  await write(QUEUE_KEY, queue);
  await broadcast();
  return job;
}

chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  handle(msg)
    .then(respond)
    .catch((e) => respond({ ok: false, error: String((e && e.message) || e) }));
  return true; // async respond
});

async function handle(msg) {
  switch (msg && msg.type) {
    case 'PING':
      return { ok: true, version: chrome.runtime.getManifest().version };
    case 'ENQUEUE': {
      const job = await enqueue(msg.job);
      const queue = await getQueue();
      // Badge the toolbar icon: the operator clicked Run in the CRM and the
      // next move is in the popup, so say so without stealing focus.
      await chrome.action.setBadgeText({ text: String(queue.length) });
      await chrome.action.setBadgeBackgroundColor({ color: '#F0613C' });
      return { ok: true, id: job.id, queued: queue.length };
    }
    case 'GET_STATE':
      return { ok: true, state: await snapshot() };
    case 'RUN':
      return await run(msg.id);
    case 'DISCARD': {
      const queue = (await getQueue()).filter((j) => j.id !== msg.id);
      await write(QUEUE_KEY, queue);
      await chrome.action.setBadgeText({ text: queue.length ? String(queue.length) : '' });
      await broadcast();
      return { ok: true };
    }
    case 'CLEAR_ACTIVE': {
      const active = await getActive();
      if (active && active.status === 'running') return { ok: false, error: 'Run in progress.' };
      await write(ACTIVE_KEY, null);
      await broadcast();
      return { ok: true };
    }
    default:
      return { ok: false, error: 'Unknown message.' };
  }
}

// ── the run ───────────────────────────────────────────────────────────────

async function backofficeTab() {
  const tabs = await chrome.tabs.query({ url: BACKOFFICE_MATCH });
  // Prefer the focused one so "which tab did that run in?" has an obvious answer.
  return tabs.find((t) => t.active) || tabs[0] || null;
}

/**
 * Fill in the MANUAL_TOKEN knob the scripts already expose.
 *
 * This is the ONLY edit made to a generated script, and it is deliberately
 * brittle: exact line, exactly one occurrence, or no edit at all. If the shape
 * ever changes, the script runs unmodified and falls back to its own token
 * capture — which still works, because we run it in the page.
 */
function seedToken(code, auth) {
  const parts = code.split(MANUAL_TOKEN_LINE);
  if (parts.length !== 2) return { code, seeded: false };
  const jwt = auth.replace(/^Bearer\s+/i, '');
  // JSON.stringify, not hand-rolled quoting: a JWT is base64url so it cannot
  // contain a quote, but never hand-roll a literal into someone else's source.
  return {
    code: parts[0] + 'const MANUAL_TOKEN = ' + JSON.stringify(jwt) + ';' + parts[1],
    seeded: true,
  };
}

async function run(jobId) {
  const existing = await getActive();
  if (existing && existing.status === 'running') {
    return { ok: false, error: 'A run is already in progress.' };
  }

  const queue = await getQueue();
  const job = queue.find((j) => j.id === jobId);
  if (!job) return { ok: false, error: 'That script is no longer queued.' };

  const tab = await backofficeTab();
  if (!tab) {
    return {
      ok: false,
      error: 'No REA backoffice tab is open. Open the backoffice, log in, then run again.',
    };
  }

  await write(ACTIVE_KEY, {
    name: job.name,
    source: job.source,
    tabId: tab.id,
    startedAt: Date.now(),
    lines: [],
    status: 'running',
    error: null,
    journeyIds: [],
  });
  await write(QUEUE_KEY, queue.filter((j) => j.id !== jobId));
  await chrome.action.setBadgeText({ text: '' });
  await broadcast();

  const auth = await currentToken();
  let code = job.code;
  if (auth) {
    const seeded = seedToken(code, auth);
    code = seeded.code;
    await log('info', seeded.seeded
      ? `Token seeded from backoffice traffic (${tokenTtl(auth)}s left). No clicking required.`
      : 'No MANUAL_TOKEN line found — the script will capture its own token; '
        + 'click anything in the backoffice if it waits.');
  } else {
    await log('warn', 'No token captured yet. The script will wait for one — click anything '
      + 'in the backoffice UI to make the page issue a request.');
  }
  await log('info', `Running ${job.name} (${code.length.toLocaleString('en-US')} bytes) in tab ${tab.id}.`);

  const target = { tabId: tab.id };
  const pending = [];
  const onEvent = (source, method, params) => {
    if (source.tabId !== tab.id) return;
    if (method === 'Runtime.consoleAPICalled') {
      const level = params.type === 'error' ? 'error'
        : params.type === 'warning' ? 'warn' : 'info';
      pending.push(log(level, formatConsoleArgs(params.args || [])));
    } else if (method === 'Runtime.exceptionThrown') {
      const d = params.exceptionDetails || {};
      const ex = d.exception || {};
      pending.push(log('error', ex.description || ex.value || d.text || 'Uncaught error'));
    }
  };

  chrome.debugger.onEvent.addListener(onEvent);
  let attached = false;
  let status = 'failed';
  let error = null;
  try {
    await chrome.debugger.attach(target, '1.3');
    attached = true;
    await chrome.debugger.sendCommand(target, 'Runtime.enable');

    const result = await chrome.debugger.sendCommand(target, 'Runtime.evaluate', {
      expression: code,
      // The scripts are a single (async () => {...})() — wait for the promise,
      // or we would report success the moment the first await yielded.
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
      // Settles the page-CSP question: the same latitude the console has.
      allowUnsafeEvalBlockedByCSP: true,
      // Runs here take minutes (fetch_games_catalog walks every provider page).
      timeout: 30 * 60 * 1000,
    });

    const details = result && result.exceptionDetails;
    if (details) {
      const ex = details.exception || {};
      throw new Error(ex.description || ex.value || details.text || 'Script threw.');
    }
    status = 'done';
  } catch (e) {
    error = String((e && e.message) || e);
  } finally {
    chrome.debugger.onEvent.removeListener(onEvent);
    // Always detach: the "being debugged" bar is Chrome's, and leaving it up
    // makes operators think something is still running.
    if (attached) await chrome.debugger.detach(target).catch(() => {});
    // Console events are delivered out of band; let the queued log writes land
    // before the final status, or the last lines appear after "Finished".
    await Promise.all(pending).catch(() => {});
  }

  if (error) await log('error', error);
  else await log('info', 'Finished.');

  const active = await getActive();
  if (active) {
    active.status = status;
    active.error = error;
    await write(ACTIVE_KEY, active);
    await broadcast();
  }
  return { ok: status === 'done', status, error };
}
