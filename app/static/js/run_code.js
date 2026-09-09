/* Adds "Get run code" to every console-script card in the admin.
 *
 * 96% of an emitted script is embedded JSON — gow_combined is 651 KB of which
 * 621 KB is payload. So instead of the operator carrying that through the
 * clipboard, the page hands the text back to the CRM, gets a short code, and
 * the operator runs a fixed five-line loader that fetches it. The loader never
 * changes, so it can live in a saved DevTools Snippet or a bookmarklet — and
 * neither of those is touched by Chrome's extension policy.
 *
 * Auto-wires by scanning for the cards the admin already renders, so none of
 * the ~10 view functions that produce a console script had to change. Same
 * detection the extension's content script uses.
 */
(function () {
  'use strict';

  var SCRIPT_AREA = 'textarea[id$="-script-text"]';
  var MARK = 'data-jbruncode';

  function nameFor(area, card) {
    var sub = card && card.querySelector('.card-head .card-sub');
    var text = sub && sub.textContent.trim();
    return text || area.id.replace(/-script-text$/, '') || 'console script';
  }

  function attach(area) {
    if (area.getAttribute(MARK)) return;
    area.setAttribute(MARK, '1');

    var card = area.closest('section.card') || area.closest('.card') || area.parentElement;
    var head = card && card.querySelector('.card-head');
    if (!head) return;

    var wrap = document.createElement('span');
    wrap.className = 'jb-run-wrap';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn primary jb-run-btn';
    btn.textContent = 'Get run code';
    btn.title = 'Hand this script to the CRM and get a code to run it with';

    var out = document.createElement('span');
    out.className = 'jb-run-out';

    btn.addEventListener('click', function () {
      btn.disabled = true;
      out.textContent = 'Working…';
      out.className = 'jb-run-out';

      fetch('/admin/tools/script-runner/job', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ name: nameFor(area, card), text: area.value }),
      })
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
            return data;
          });
        })
        .then(function (data) {
          out.textContent = '';
          out.className = 'jb-run-out jb-run-ok';

          var code = document.createElement('code');
          code.className = 'jb-run-code';
          code.textContent = data.code;
          code.title = 'Click to copy';
          code.addEventListener('click', function () {
            if (navigator.clipboard) navigator.clipboard.writeText(data.code);
            code.classList.add('jb-run-copied');
            setTimeout(function () { code.classList.remove('jb-run-copied'); }, 1200);
          });

          var note = document.createElement('span');
          var mins = Math.max(1, Math.round(data.expires_in / 60));
          note.className = 'jb-run-note';
          note.textContent = 'run it within ' + mins + ' min';

          out.appendChild(code);
          out.appendChild(note);
        })
        .catch(function (e) {
          out.textContent = e.message || String(e);
          out.className = 'jb-run-out jb-run-err';
        })
        .then(function () { btn.disabled = false; });
    });

    wrap.appendChild(btn);
    wrap.appendChild(out);

    // Left of "Copy script", which stays as the fallback.
    var copy = head.querySelector('button[id$="-copy"]');
    if (copy) copy.parentElement.insertBefore(wrap, copy);
    else head.appendChild(wrap);
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var found = scope.querySelectorAll(SCRIPT_AREA);
    for (var i = 0; i < found.length; i++) attach(found[i]);
  }

  function start() {
    scan(document);
    // Script cards arrive with htmx swaps and after form posts.
    document.addEventListener('htmx:afterSwap', function (e) { scan(e.target); });
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        Array.prototype.forEach.call(r.addedNodes, function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches && node.matches(SCRIPT_AREA)) attach(node);
          else scan(node);
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
