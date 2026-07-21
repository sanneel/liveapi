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
(async () => {
  const BASE = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0";
  const ACT = "/journey-activities/free-spins-bonus-deposit/data";
  const BRAND = "JBCL";
  const PRODUCT_TYPES = ["slots"];        // extend if you run non-slot freespins
  const FREESPIN_TYPES = ["instant", ""]; // "" = no filter; merged + de-duped

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
  const getJson = async (url) => { const r = await fetch(url, { headers:H, credentials:'include' }); if(!r.ok) throw new Error('HTTP '+r.status+' '+url); return r.json(); };

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

  for (const pt of PRODUCT_TYPES) {
    for (const fst of FREESPIN_TYPES) {
      const fq = (extra) => `${BASE}${ACT}` + extra + `&productType=${pt}` + (fst?`&freeSpinTypes=${fst}`:'');
      let providers = [];
      try { providers = await getJson(fq('/providers?_=1').replace('/providers?_=1','/providers?x=1')); }
      catch(e){ console.warn('providers fetch failed for', pt, fst, e.message); continue; }
      for (const prov of providers) {
        const pid = prov.lobbyId || prov.gameProvider || prov.id;
        if (!pid) continue;
        let page = 0, got = 100;
        while (got === 100 && page < 50) {          // 50-page safety cap
          let batch = [];
          try { batch = await getJson(fq(`/games?gameProvider=${encodeURIComponent(pid)}&page=${page}&size=100`)); }
          catch(e){ console.warn('games fetch failed', pid, 'page', page, e.message); break; }
          const items = Array.isArray(batch) ? batch : (batch.data || batch.items || []);
          got = items.length;
          for (const g of items) { if (g && g.lobbyId) games[g.lobbyId] = norm(g); }
          console.log(`  ${pt}/${fst||'all'} ${pid}: page ${page} → ${got} (total ${Object.keys(games).length})`);
          page++;
        }
      }
    }
  }

  const sorted = {}; Object.keys(games).sort().forEach(k => sorted[k] = games[k]);
  const out = { _doc: "Games registry — generated live from the backoffice catalog API by fetch_games_catalog_console.js.", games: sorted };
  const json = JSON.stringify(out, null, 2);
  console.log('%cDONE: '+Object.keys(sorted).length+' games.','color:#22c55e;font-weight:bold');
  try { copy(json); console.log('Copied games.json to clipboard — paste into journey-cloner/library/games.json'); } catch(e) { console.log('Clipboard blocked; JSON below:'); }
  console.log(json);
  window.__gamesRegistry = out;
})();
