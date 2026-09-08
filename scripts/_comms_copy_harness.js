// Stubs enough of a browser and of the backoffice to run a generated
// comms_copy_update console script end to end, then prints what the script
// would have saved. Driven by scripts/test_comms_copy_update.py.
'use strict';
const fs = require('fs');

const scriptPath = process.argv[2];
const draftPath = process.argv[3];
const outPath = process.argv[4];

const draft = JSON.parse(fs.readFileSync(draftPath, 'utf-8'));
const saved = { put: null, contents: [], published: [], uploads: [] };

const b64u = (o) => Buffer.from(JSON.stringify(o)).toString('base64')
  .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const JWT = b64u({ alg: 'HS256' }) + '.'
  + b64u({ typ: 'Bearer', exp: Math.floor(Date.now() / 1000) + 3600 }) + '.sig';

let uploadSeq = 0;
async function server(url, opts) {
  const method = (opts && opts.method) || 'GET';
  const body = () => JSON.parse(opts.body);
  const ok = (obj) => ({ ok: true, status: 200, text: async () => JSON.stringify(obj) });

  if (/\/journey-drafts\/\d+$/.test(url) && method === 'GET') return ok(saved.put || draft);
  if (/\/journey-drafts\/\d+$/.test(url) && method === 'PUT') { saved.put = body(); return ok({}); }
  if (/\/media-library\/v0\/folder\/.*\/upload\//.test(url)) {
    uploadSeq += 1;
    const id = 'asset-' + uploadSeq;
    saved.uploads.push(url);
    return ok({ id, absolute_link: 'https://cdn.example/' + id + '.png',
                relative_link: '/folder/' + id + '.png' });
  }
  if (/\/media-library\/v0\/asset\/thumb\//.test(url)) return ok({});
  if (/\/email\/contents$/.test(url) && method === 'POST') {
    saved.contents.push(body());
    return ok({ id: 'CSE-0-99999' });
  }
  if (/\/email\/contents\/[^/]+$/.test(url) && method === 'POST') { saved.contents.push(body()); return ok({}); }
  if (/\/email\/contents\/[^/]+\/publish$/.test(url) && method === 'PATCH') {
    saved.published.push(url); return ok({});
  }
  return { ok: false, status: 404, text: async () => 'no stub for ' + method + ' ' + url };
}

globalThis.window = globalThis;
globalThis.fetch = async (input, init) => server(typeof input === 'string' ? input : input.url, init || {});
globalThis.XMLHttpRequest = function () {};
globalThis.XMLHttpRequest.prototype.open = function () {};
globalThis.XMLHttpRequest.prototype.setRequestHeader = function () {};
globalThis.FormData = function () { this.append = () => {}; };
globalThis.URL.createObjectURL = () => 'blob:stub';
globalThis.URL.revokeObjectURL = () => {};
globalThis.Image = class {
  constructor() { this.naturalWidth = 640; this.naturalHeight = 480; }
  set src(_v) { setTimeout(() => this.onload && this.onload(), 0); }
};

// The picker: every created <input type=file> fires `change` with one file, so
// the script's browse step runs unattended.
let pickSeq = 0;
const el = (tag) => ({
  tag, style: {}, children: [], _listeners: {},
  appendChild(c) { this.children.push(c); },
  remove() {},
  addEventListener(ev, fn) {
    this._listeners[ev] = fn;
    if (this.tag === 'input') {
      pickSeq += 1;
      const name = 'photo-' + pickSeq + '.png';
      setTimeout(() => { this.files = [{ name, size: 1234 }]; fn(); }, 0);
    }
  },
});
globalThis.document = { createElement: el, body: el('body') };

// The script waits for the page to make an authorized request before it starts.
setTimeout(() => {
  globalThis.fetch('https://pmi.rea-backoffice.gr8.tech/api/core/api/v0/crm/ping',
                   { headers: { authorization: 'Bearer ' + JWT } });
}, 5);

const logs = [];
for (const level of ['log', 'warn', 'error']) {
  const orig = console[level].bind(console);
  console[level] = (...a) => { logs.push(a.map(String).join(' ')); orig(...a); };
}

(async () => {
  try {
    await eval(fs.readFileSync(scriptPath, 'utf-8'));
    // The script's IIFE is not awaited by eval; give its async chain time to finish.
    await new Promise((r) => setTimeout(r, 200));
  } catch (e) {
    saved.error = String((e && e.message) || e);
  }
  saved.logs = logs;
  fs.writeFileSync(outPath, JSON.stringify(saved, null, 2));
})();
