#!/usr/bin/env python3
"""Paste-time JavaScript shared by every console-script generator.

One copy of the JSON response guard, the media-library upload and the
create-then-save of a journey draft, so a fix lands in every generator at once
instead of in the hand-rolled copies this replaced.

A generator puts the tokens it needs inside its JS_TEMPLATE and runs the
template through ``inject``:

    JS_TEMPLATE = inject(JS_TEMPLATE)

``@JSON_GUARD_JS@``    parseJsonText / readJson, needed by the other two.
``@MEDIA_UPLOAD_JS@``  the photo upload; expects ``CRM_BASE``, ``FOLDER_ID``
                       and ``imageDims`` in the enclosing scope.
``@DRAFT_SAVE_JS@``    createAndSaveDraft; expects ``BASE``.

Both helpers take the script's own header builder (``headers`` or ``H``) as an
argument, so they drop in under either naming.
"""

from __future__ import annotations

# The backoffice moved its CRM gateway: the page now calls /api/core/..., while
# every generator here has hard-coded /api/ubo/... since the first capture. The
# prefix is no longer ours to bake in, so each run reads it off the page's own
# traffic (the resource-timing buffer the browser already keeps) and only falls
# back to the baked-in value when the buffer says nothing.
API_BASE_JS = r"""  const CRM_ROOT_RE = /^(https?:\/\/[^/]+\/api\/[A-Za-z0-9_-]+\/api\/v0\/crm)(\/|$)/;

  function apiBase(fallback) {
    const marker = '/api/v0/crm';
    const cut = fallback.indexOf(marker);
    if (cut < 0) return fallback;
    const tail = fallback.slice(cut + marker.length);
    const counts = new Map();
    try {
      for (const e of performance.getEntriesByType('resource')) {
        const m = CRM_ROOT_RE.exec(e.name);
        if (m) counts.set(m[1], (counts.get(m[1]) || 0) + 1);
      }
    } catch (e) {}
    if (!counts.size) {
      console.warn('%cNo backoffice API calls in the page history yet, using the baked-in ' + fallback + '. If a call 404s or 405s, click around the UI once and rerun.', 'color:#eab308');
      return fallback;
    }
    const live = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0] + tail;
    if (live !== fallback) {
      console.warn('%cThis page calls ' + live + ', not ' + fallback + '. Following the page.', 'color:#eab308');
    }
    return live;
  }
"""

JSON_GUARD_JS = r"""  function parseJsonText(text, label, status) {
    const t = (text || '').trim();
    if (!t) throw new Error(label + ' returned an empty body (HTTP ' + status + ').');
    if (t[0] === '<') throw new Error(label + ' returned HTML, not JSON (HTTP ' + status + '). Wrong route, or the backoffice tab is logged out.');
    try { return JSON.parse(t); } catch (e) { throw new Error(label + ' returned unparseable JSON (HTTP ' + status + '): ' + t.slice(0, 200)); }
  }

  async function readJson(r, label) {
    const text = await r.text();
    if (!r.ok) throw new Error(label + ' HTTP ' + r.status + ' ' + text.slice(0, 400));
    return parseJsonText(text, label, r.status);
  }

"""

# Why the route ladder: the captured upload is
#   PUT <crm>/media-library/v0/folder/<uuid>/upload/<name>.png?height=H&width=W
# and it answered 405 for a photo whose file name carried a space and
# brackets ("360x330 (33).png"). The name is slugged first, which is what
# normally fixes it. If the documented route still refuses, the remaining
# combinations are tried once each and the one that worked is printed, so the
# generator can be corrected from evidence rather than the run falling back to
# the captured campaign's artwork.
MEDIA_UPLOAD_JS = r"""  function assetName(file, fallback) {
    const raw = ((file && file.name) || fallback || 'image').replace(/\.[^./]+$/, '');
    const slug = raw.normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^0-9A-Za-z._-]+/g, '-').replace(/-{2,}/g, '-')
      .replace(/^[-._]+|[-._]+$/g, '').slice(0, 60);
    return (slug || fallback || 'image') + '.png';
  }

  async function uploadToMediaLibrary(file, label, hdrs) {
    if (!FOLDER_ID) throw new Error(label + ': no media-library FOLDER_ID is set, nothing to upload into.');
    const dims = await imageDims(file);
    const name = assetName(file, 'image');
    const query = '?height=' + dims.height + '&width=' + dims.width;
    const bases = [CRM_BASE];
    for (const prefix of ['/api/core/', '/api/ubo/']) {
      const alt = CRM_BASE.replace(/\/api\/[A-Za-z0-9_-]+\/api\/v0\/crm/, prefix + 'api/v0/crm');
      if (!bases.includes(alt)) bases.push(alt);
    }
    const tried = [];
    for (const base of bases) {
      for (const method of ['PUT', 'POST']) {
        const url = base + '/media-library/v0/folder/' + FOLDER_ID + '/upload/' + encodeURIComponent(name) + query;
        const fd = new FormData();
        fd.append('file', file, name);
        let r;
        try {
          r = await fetch(url, { method: method, headers: hdrs(), credentials: 'include', body: fd });
        } catch (e) {
          tried.push(method + ' ' + base + ' threw ' + ((e && e.message) || e));
          continue;
        }
        if (r.status === 401 || r.status === 403) {
          throw new Error(label + ' upload rejected HTTP ' + r.status + '. The captured token may not write to folder ' + FOLDER_ID + ' on this brand.');
        }
        if (!r.ok) { tried.push(method + ' ' + base + ' HTTP ' + r.status); continue; }
        const asset = await readJson(r, label + ' upload');
        if (!asset || !asset.id || !asset.absolute_link || !asset.relative_link) {
          throw new Error(label + ' upload returned no asset link: ' + JSON.stringify(asset).slice(0, 300));
        }
        if (tried.length) {
          console.warn('%c    ' + label + ': the captured upload route failed (' + tried.join('; ') + '). ' + method + ' on ' + base + ' worked. Report that line so the generator can bake it in.', 'color:#eab308');
        }
        const tfd = new FormData();
        tfd.append('file', file, name);
        await fetch(base + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: method, headers: hdrs(), credentials: 'include', body: tfd }).catch(() => {});
        console.log('    ' + label + ' uploaded ' + asset.id + ' -> ' + asset.absolute_link);
        return asset;
      }
    }
    throw new Error(label + ' upload failed on every known route: ' + tried.join('; ') + '. Upload one photo by hand in the backoffice with the Network tab open, filter on "upload", and send the request line.');
  }
"""


# The draft is only half made by the POST: the builder finalises the canvas on
# the PUT that follows, and a draft created without it opens with its nodes
# unconnected. Both bodies are identical, which is what the backoffice itself
# sends.
DRAFT_SAVE_JS = r"""  async function createAndSaveDraft(body, label, hdrs) {
    const jsonHeaders = Object.assign({}, hdrs(), { 'content-type': 'application/json' });
    const payload = JSON.stringify(body);
    const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: jsonHeaders, credentials: 'include', body: payload });
    const resp = await r.text();
    if (!r.ok) throw new Error(label + ' draft not created: HTTP ' + r.status + ' ' + resp);
    const numId = parseJsonText(resp, label + ' draft create', r.status).id;
    if (!numId) throw new Error(label + ' draft create returned no id: ' + resp.slice(0, 300));
    const rs = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: jsonHeaders, credentials: 'include', body: payload });
    if (!rs.ok) throw new Error(label + ' draft ' + numId + ' was created but the save failed: HTTP ' + rs.status + ' ' + (await rs.text()) + '. Delete that half-made draft before rerunning.');
    return numId;
  }
"""


def inject(js: str) -> str:
    """Substitute whichever shared blocks a JS_TEMPLATE asks for."""
    for token, block in (
        ("@API_BASE_JS@", API_BASE_JS),
        ("@JSON_GUARD_JS@", JSON_GUARD_JS),
        ("@MEDIA_UPLOAD_JS@", MEDIA_UPLOAD_JS),
        ("@DRAFT_SAVE_JS@", DRAFT_SAVE_JS),
    ):
        js = js.replace(token, block)
    return js
