// Popup: token status, the queue, and the live log of the current run.
//
// The log replaces what the operator used to read in the DevTools console. Every
// console.log the script makes still lands here, verbatim — including the
// refusals, which is the point. A run that stops early must look stopped, not
// quietly finished.

const $ = (id) => document.getElementById(id);

const send = (msg) => chrome.runtime.sendMessage(msg);

let lastLineCount = 0;

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

function fmtAgo(ts) {
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function renderToken(token) {
  const el = $('token');
  if (!token || !token.present) {
    el.textContent = 'no token yet';
    el.className = 'pill warn';
    el.title = 'Open a logged-in backoffice tab and click around once; the token '
      + 'is read from the page’s own requests.';
    return;
  }
  const mins = Math.floor(token.ttl / 60);
  el.textContent = `token ok · ${mins}m left`;
  el.className = 'pill ok';
  el.title = 'Captured from backoffice traffic. Seeded into the script so it '
    + 'never has to wait for one.';
}

function renderQueue(queue) {
  const ul = $('queue');
  ul.textContent = '';
  $('queue-empty').hidden = queue.length > 0;

  for (const job of queue) {
    const li = document.createElement('li');

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = job.name;
    name.title = job.source;

    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = `${fmtBytes(job.bytes)} · ${fmtAgo(job.receivedAt)}`;

    const run = document.createElement('button');
    run.className = 'primary';
    run.textContent = 'Run';
    run.addEventListener('click', async () => {
      run.disabled = true;
      $('err').textContent = '';
      const res = await send({ type: 'RUN', id: job.id });
      // A refused run leaves the job queued, so the operator can fix the cause
      // (open the backoffice, log in) and press Run again.
      if (res && !res.ok && res.error) $('err').textContent = res.error;
      run.disabled = false;
    });

    const drop = document.createElement('button');
    drop.textContent = 'Discard';
    drop.addEventListener('click', () => send({ type: 'DISCARD', id: job.id }));

    li.append(name, meta, run, drop);
    ul.append(li);
  }
}

function renderRun(active) {
  const section = $('run-section');
  section.hidden = !active;
  if (!active) { lastLineCount = 0; return; }

  $('run-name').textContent = active.name;

  const status = $('run-status');
  const label = { running: 'running', done: 'done', failed: 'failed' }[active.status] || active.status;
  status.textContent = label;
  status.className = 'pill ' + ({ running: 'busy', done: 'ok', failed: 'err' }[active.status] || '');

  const ids = $('ids');
  ids.textContent = '';
  ids.hidden = !active.journeyIds.length;
  for (const id of active.journeyIds) {
    const code = document.createElement('code');
    code.textContent = id;
    ids.append(code);
  }

  const log = $('log');
  // Append-only while a run streams; rebuild if the log was trimmed or replaced.
  const grew = active.lines.length >= lastLineCount && log.childNodes.length === lastLineCount;
  if (!grew) { log.textContent = ''; lastLineCount = 0; }
  for (const line of active.lines.slice(lastLineCount)) {
    const span = document.createElement('span');
    span.className = line.level;
    span.textContent = line.text + '\n';
    log.append(span);
  }
  lastLineCount = active.lines.length;

  if ($('tail').checked) log.scrollTop = log.scrollHeight;

  $('clear').disabled = active.status === 'running';
}

function render(state) {
  renderToken(state.token);
  renderQueue(state.queue);
  renderRun(state.active);
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === 'STATE') render(msg.state);
});

$('clear').addEventListener('click', () => send({ type: 'CLEAR_ACTIVE' }));
$('opts').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

send({ type: 'GET_STATE' }).then((res) => {
  if (res && res.ok) render(res.state);
  else $('err').textContent = (res && res.error) || 'Could not reach the extension worker.';
});

// Token TTL and "3m ago" go stale while the popup sits open.
setInterval(() => {
  send({ type: 'GET_STATE' }).then((res) => { if (res && res.ok) render(res.state); });
}, 10000);
