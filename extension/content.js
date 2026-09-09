// Injected into the Jugabet CRM admin. Adds a "Run in backoffice" button to
// every rendered console-script card and hands the text to the service worker.
//
// Nothing server-side changes. The admin already renders the full script into
// <textarea id="*-script-text"> next to a "Copy script" button, so the text is
// right there in the DOM — the extension only has to notice it and offer a
// better verb than "copy". Install the extension and the buttons appear;
// uninstall it and the pages are exactly as they were.
//
// NOTE: MV3 content scripts are not modules, so the two constants shared with
// config.js are repeated here. Keep them in sync.

(() => {
  'use strict';

  // Cards the admin renders for a generated script. See
  // app/templates/promotions.html and app/templates/partials/_*_form.html.
  const SCRIPT_AREA = 'textarea[id$="-script-text"]';
  const MARK = 'data-jbrunner';

  function nameFor(area, card) {
    // The card head carries the generated filename, e.g. "GOW_console.js".
    const sub = card && card.querySelector('.card-head .card-sub');
    const text = sub && sub.textContent.trim();
    if (text) return text;
    // Fall back to the textarea id: "pred-script-text" -> "pred".
    return area.id.replace(/-script-text$/, '') || 'console script';
  }

  function button(label, title) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn primary jb-runner-btn';
    b.textContent = label;
    b.title = title;
    return b;
  }

  function status(text, kind) {
    const s = document.createElement('span');
    s.className = 'jb-runner-status jb-runner-' + (kind || 'info');
    s.textContent = text;
    return s;
  }

  function attach(area) {
    if (area.getAttribute(MARK)) return;
    area.setAttribute(MARK, '1');

    const card = area.closest('section.card') || area.closest('.card') || area.parentElement;
    const head = card && card.querySelector('.card-head');
    if (!head) return;

    const name = nameFor(area, card);
    const run = button('Run in backoffice', 'Send this script to the Script Runner extension');
    const note = status('', 'info');

    run.addEventListener('click', async () => {
      run.disabled = true;
      note.textContent = 'Sending…';
      note.className = 'jb-runner-status jb-runner-info';
      try {
        const res = await chrome.runtime.sendMessage({
          type: 'ENQUEUE',
          job: { name, code: area.value, source: location.href },
        });
        if (!res || !res.ok) throw new Error((res && res.error) || 'Extension did not respond.');
        note.textContent = 'Queued — open the Script Runner to start it.';
        note.className = 'jb-runner-status jb-runner-ok';
      } catch (e) {
        // The usual cause is the worker having been reloaded mid-session; the
        // Copy button is untouched, so say what still works.
        note.textContent = (e && e.message) || String(e);
        note.className = 'jb-runner-status jb-runner-err';
      } finally {
        run.disabled = false;
      }
    });

    // Sit left of "Copy script" so Run reads as the primary action but Copy is
    // never taken away — it is the fallback whenever a run misbehaves.
    const copy = head.querySelector('button[id$="-copy"]');
    const wrap = document.createElement('span');
    wrap.className = 'jb-runner-wrap';
    wrap.append(run, note);
    if (copy) {
      copy.classList.add('jb-runner-demoted');
      copy.parentElement.insertBefore(wrap, copy);
    } else {
      head.append(wrap);
    }
  }

  function scan(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(SCRIPT_AREA).forEach(attach);
  }

  scan(document);

  // The admin swaps panels in with htmx (see base.html), so a script card can
  // appear long after load.
  document.addEventListener('htmx:afterSwap', (e) => scan(e.target));
  new MutationObserver((records) => {
    for (const r of records) {
      for (const node of r.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.matches && node.matches(SCRIPT_AREA)) attach(node);
        else scan(node);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
