// Games catalog fetcher — pulls the FULL live games registry from the REA
// backoffice, the same API the Journey Builder UI uses to find game ids.
//
// Paste into a logged-in backoffice console (F12). It captures the token,
// lists providers, pages through every provider's games, and prints a JSON
// object keyed by lobbyId — ready to save as journey-cloner/library/games.json
// (or feed to build_games_registry.py). Also copies it to the clipboard.
//
// How a game id is found (what this automates): the UI GETs
//   /journey-activities/free-spins-bonus-deposit/data/providers?productType=slots
//   /journey-activities/free-spins-bonus-deposit/data/games?gameProvider=<p>&productType=slots&page=<n>&size=100
// then stores the chosen game's lobbyId/walletId/externalGameId on the activity.
//
// RATE LIMITING: this walks every provider page by page — hundreds of requests
// back to back, which is enough to get throttled or temporarily blocked. Every
// request is spaced by THROTTLE_MS and retried with exponential backoff on 429
// and 5xx, honouring Retry-After when the server sends it. If you still see
// 429s, raise THROTTLE_MS; the run is unattended anyway.
(async () => {
  const BASE = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0";
  const ACT = "/journey-activities/free-spins-bonus-deposit/data";
  const BRAND = "JBCL";
  const PRODUCT_TYPES = ["slots"];        // extend if you run non-slot freespins
  const FREESPIN_TYPES = ["instant", ""]; // "" = no filter; merged + de-duped

  // ---- pacing knobs -------------------------------------------------------
  const THROTTLE_MS  = 400;    // minimum gap between two requests
  const JITTER_MS    = 150;    // random extra so retries don't sync up
  const MAX_RETRIES  = 5;      // per request, on 429/5xx/network error
  const BACKOFF_BASE = 1000;   // 1s, 2s, 4s, 8s, 16s
  const MAX_BACKOFF  = 30000;
  const PAGE_CAP     = 50;     // safety cap per provider

  const sleep  = (ms) => new Promise(r => setTimeout(r, ms));
  const jitter = () => THROTTLE_MS + Math.floor(Math.random() * JITTER_MS);

  let lastRequestAt = 0, requestCount = 0, retryCount = 0;

  // fetch() is not rate-limited by the browser, so without this the loops below
  // fire as fast as the network allows.
  async function pace() {
    const wait = lastRequestAt + jitter() - Date.now();
    if (wait > 0) await sleep(wait);
    lastRequestAt = Date.now();
  }

  async function getJson(url) {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      await pace();
      let r;
      try {
        r = await fetch(url, { headers: H, credentials: 'include' });
      } catch (netErr) {
        // Network blip: back off rather than abort a run that may already be
        // several minutes in.
        if (attempt === MAX_RETRIES) throw netErr;
        const d = Math.min(BACKOFF_BASE * (2 ** attempt), MAX_BACKOFF);
        retryCount++;
        console.warn(`  network error, retry ${attempt + 1}/${MAX_RETRIES} in ${d}ms — ${netErr.message}`);
        await sleep(d);
        continue;
      }
      requestCount++;
      if (r.ok) return r.json();

      const retryable = r.status === 429 || r.status >= 500;
      if (!retryable || attempt === MAX_RETRIES) throw new Error('HTTP ' + r.status + ' ' + url);

      let delay = Math.min(BACKOFF_BASE * (2 ** attempt), MAX_BACKOFF);
      const ra = r.headers.get('retry-after');       // seconds, or an HTTP-date
      if (ra) {
        const ms = /^\d+$/.test(ra.trim()) ? parseInt(ra, 10) * 1000 : (Date.parse(ra) - Date.now());
        if (ms > 0) delay = Math.min(Math.max(ms, delay), MAX_BACKOFF * 4);
      }
      retryCount++;
      console.warn(`  HTTP ${r.status}, retry ${attempt + 1}/${MAX_RETRIES} in ${delay}ms`);
      await sleep(delay);
    }
    throw new Error('unreachable');
  }

  function decodeJwt(t){ try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch(e){ return null; } }
  function usableAuth(v){ if(!v || !/^Bearer\s+\S+/i.test(v)) return null; const p=decodeJwt(v.replace(/^Bearer\s+/i,'')); if(!p||p.typ!=='Bearer') return null; return 'Bearer '+v.replace(/^Bearer\s+/i,''); }
  function obtainAuth(){ return new Promise((resolve,reject)=>{
    let settled=false; const of=window.fetch; const os=XMLHttpRequest.prototype.setRequestHeader;
    const cleanup=()=>{ window.fetch=of; XMLHttpRequest.prototype.setRequestHeader=os; };
    const consider=(v)=>{ const a=usableAuth(v); if(a&&!settled){ settled=true; cleanup(); clearTimeout(t); console.log('%cToken captured.','color:#22c55e;font-weight:bold'); resolve(a); } };
    window.fetch=function(input,init){ try{ const h=(init&&init.headers)||(input&&input.headers); if(h){ if(typeof h.get==='function') consider(h.get('authorization')); else consider(h.authorization||h.Authorization); } }catch(e){} return of.apply(this,arguments); };
    XMLHttpRequest.prototype.setRequestHeader=function(n,v){ try{ if(/^authorization$/i.test(n)) consider(v); }catch(e){} return os.apply(this,arguments); };
    const t=setTimeout(()=>{ if(!settled){ settled=true; cleanup(); reject(new Error('No token in 3 min. Click around and re-run.')); } },180000);
    console.log('%cWaiting for a token — click anything in the backoffice UI.','color:#eab308;font-weight:bold');
  }); }

  const auth = await obtainAuth();
  const H = { accept:'application/json, text/plain, */*', authorization:auth, 'x-brand':BRAND };

  const games = {};
  const norm = (g) => ({
    provider: g.gameProvider, lobbyGameId: g.lobbyId,
    walletGameId: g.walletId, externalGameId: g.externalGameId,
    productType: (g.productTypes||[])[0] || null,
    gameTranslationKey: g.translationKey,
    contributionFactor: g.contributionFactor,
    freeSpinsAvailable: g.freeSpinsAvailable, status: g.status,
    aliases: [ (g.translationKey||'').trim().toLowerCase() ].filter(Boolean),
  });

  const startedAt = Date.now();
  console.log(`%cPacing ${THROTTLE_MS}-${THROTTLE_MS + JITTER_MS}ms between requests, up to ${MAX_RETRIES} retries each. Slow on purpose — leave the tab open.`, 'color:#eab308');

  for (const pt of PRODUCT_TYPES) {
    for (const fst of FREESPIN_TYPES) {
      const fq = (extra) => `${BASE}${ACT}` + extra + `&productType=${pt}` + (fst?`&freeSpinTypes=${fst}`:'');
      let providers = [];
      try { providers = await getJson(fq('/providers?x=1')); }
      catch(e){ console.warn('providers fetch failed for', pt, fst, e.message); continue; }
      console.log(`%c${pt}/${fst||'all'}: ${providers.length} providers`, 'color:#60a5fa;font-weight:bold');

      for (let i = 0; i < providers.length; i++) {
        const pid = providers[i].lobbyId || providers[i].gameProvider || providers[i].id;
        if (!pid) continue;
        let page = 0, got = 100;
        while (got === 100 && page < PAGE_CAP) {
          let batch = [];
          try { batch = await getJson(fq(`/games?gameProvider=${encodeURIComponent(pid)}&page=${page}&size=100`)); }
          catch(e){ console.warn('games fetch failed', pid, 'page', page, e.message); break; }
          const items = Array.isArray(batch) ? batch : (batch.data || batch.items || []);
          got = items.length;
          for (const g of items) { if (g && g.lobbyId) games[g.lobbyId] = norm(g); }
          page++;
        }
        const elapsed = ((Date.now() - startedAt) / 1000).toFixed(0);
        console.log(`  [${i + 1}/${providers.length}] ${pid}: ${page} page(s) — ${Object.keys(games).length} games so far (${elapsed}s, ${requestCount} reqs, ${retryCount} retries)`);
      }
    }
  }

  const sorted = {}; Object.keys(games).sort().forEach(k => sorted[k] = games[k]);
  const out = { _doc: "Games registry — generated live from the backoffice catalog API by fetch_games_catalog_console.js.", games: sorted };
  const json = JSON.stringify(out, null, 2);
  const mins = ((Date.now() - startedAt) / 60000).toFixed(1);
  console.log(`%cDONE: ${Object.keys(sorted).length} games in ${mins} min (${requestCount} requests, ${retryCount} retries).`, 'color:#22c55e;font-weight:bold');
  // Per-provider counts, so you can see at a glance whether Tada / 3oaks arrived.
  const byProvider = {};
  Object.values(sorted).forEach(g => { byProvider[g.provider] = (byProvider[g.provider] || 0) + 1; });
  console.log('Games per provider:', byProvider);
  try { copy(json); console.log('Copied to clipboard — save as journey-cloner/library/games.json, then rebuild the compact index.'); }
  catch(e) { console.log('Clipboard blocked; JSON below:'); }
  console.log(json);
  window.__gamesRegistry = out;
})();
