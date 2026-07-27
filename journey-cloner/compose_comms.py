#!/usr/bin/env python3
"""COMPOSE (not clone) a comms journey — proven to render + save in REA.

Chain:  dwh_source -> notification_center -> notification_center
        -> dextra_sms -> dextra_email -> end_of_journey

Every node, config, edge and the shell are taken from ONE real comms journey
that renders (gow_comms), then rewired into this chain with fresh ids and an
auto-layout. Sourcing from a single rendering journey avoids node-schema mixing
(the blank-canvas trap). See COMPOSER_RULES.md for the full rule set learned
here (position+positionAbsolute on every node, de-nest parentNode, keep edge
eventDisplayName/payloadKeys, set a start trigger).

Emits console_scripts/comms_composed_console.js — paste into a logged-in
backoffice tab. It captures the token, reserves a JRN id, freshens ids, and
POSTs one draft.
"""
from __future__ import annotations

import copy
import datetime
import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAG = HERE / "library" / "fragments"
OUT = HERE / "console_scripts"
SHELL = HERE / "templates" / "casino" / "nc_discount.json"
BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
BRAND = "JBCL"

# (fragment, primary completion event, its eventType) — the forward edge.
CHAIN = [
    ("dwh_source",          "PlayerAdded",      "Activation"),
    ("notification_center", "NotificationSent", "Completion"),
    ("notification_center", "NotificationSent", "Completion"),
    ("dextra_sms",          "SuccessSmsSend",   "Completion"),
    ("dextra_email",        "SuccessEmailSend", "Completion"),
]
LABELS = {
    "dwh_source": "Segment — comms test",
    "notification_center": "On-site notification",
    "dextra_sms": "SMS",
    "dextra_email": "Email",
}


def _load(name: str) -> dict:
    return json.load(open(FRAG / f"{name}.json", encoding="utf-8"))


def _nid() -> str:
    return str(uuid.uuid4())


def _swap(obj, old: str, new: str):
    """Regenerate an id everywhere it's embedded (ports/handles included)."""
    return json.loads(json.dumps(obj, ensure_ascii=False).replace(old, new))


REF = HERE / "templates" / "casino" / "gow_comms.json"   # a comms journey that RENDERS


def _ref_body() -> dict:
    b = json.load(open(REF, encoding="utf-8"))
    return b.get("body", b)


def build_body() -> tuple[dict, str, list]:
    """Reproduce a rendering journey's exact node/edge shapes. Every node,
    config, edge and the shell come from ONE real comms journey (gow_comms) so
    there is zero schema mixing — we only rewire the chain and regenerate ids."""
    ref = _ref_body()
    by_name: dict = {}
    for a in ref["activities"]:
        by_name.setdefault(a.get("activityName"), a)          # first of each type
    ref_cfg = ref["rawJourneyData"].get("activitiesConfiguration", {}) or {}
    ref_els = ref["rawJourneyData"]["elements"]
    node_by_id = {e["id"]: e for e in ref_els
                  if e.get("type") in ("source", "action", "exit")}
    edge_tpl = next(e for e in ref_els if e.get("type") == "default")

    insts = []
    for name, primary, ptype in CHAIN:
        a = by_name[name]
        insts.append({"name": name, "primary": primary, "ptype": ptype,
                      "old": a["activityId"], "aid": _nid()})
    end_a = by_name["end_of_journey"]
    end_old, end_aid = end_a["activityId"], _nid()
    chain_ids = [x["aid"] for x in insts] + [end_aid]

    activities, acts_cfg, elements = [], {}, []

    def place(node_el, old, new, i):
        el = _swap(node_el, old, new)
        el["id"] = new
        pos = {"x": 0, "y": i * 170}
        el["position"] = dict(pos)
        el["positionAbsolute"] = dict(pos)     # editor reads positionAbsolute.x
        el.pop("parentNode", None)             # de-nest (gow_comms NC sits in a
        el.pop("extent", None)                 # boundary container we don't have)
        return el

    for i, nd in enumerate(insts):
        old, aid = nd["old"], nd["aid"]
        act = _swap(by_name[nd["name"]], old, aid)
        nxt = chain_ids[i + 1]
        for ev in act.get("events", []) or []:
            ev["nextActivityId"] = nxt if ev.get("eventName") == nd["primary"] else None
        activities.append(act)
        if old in ref_cfg:
            acts_cfg[aid] = _swap(ref_cfg[old], old, aid)
        elements.append(place(node_by_id[old], old, aid, i))

    # terminal — reuse gow_comms' own end_of_journey node + activity
    end_act = _swap(end_a, end_old, end_aid)
    end_act["events"] = []
    activities.append(end_act)
    if end_old in node_by_id:
        elements.append(place(node_by_id[end_old], end_old, end_aid, len(insts)))
    else:
        elements.append({
            "id": end_aid,
            "data": {"name": "end_of_journey",
                     "ports": [{"id": f"input-{end_aid}"}], "width": 40, "height": 40},
            "type": "exit", "style": {"cursor": "default"}, "width": 40, "height": 40,
            "hidden": False, "zIndex": 5,
            "position": {"x": 0, "y": len(insts) * 170},
            "positionAbsolute": {"x": 0, "y": len(insts) * 170},
            "selected": False, "draggable": False, "connectable": False,
        })

    # forward edges (primary chain) — stamped from a real gow_comms edge so they
    # keep eventDisplayName/payloadKeys the renderer expects
    for i, nd in enumerate(insts):
        frm, to = nd["aid"], chain_ids[i + 1]
        e = copy.deepcopy(edge_tpl)
        e["id"] = _nid()
        e["source"], e["target"] = frm, to
        e["sourceHandle"] = f"{nd['primary']}-{frm}"
        e["targetHandle"] = f"input-{to}"
        d = e.setdefault("data", {})
        d["eventName"], d["eventType"], d["activityName"] = nd["primary"], nd["ptype"], nd["name"]
        elements.append(e)

    # shell = gow_comms itself (a rendering comms journey)
    shell = _ref_body()
    for k in ("duplicatedFromId", "duplicatedFromVersion", "changeHistory"):
        shell.pop(k, None)

    name = f"JBCL | CS | COMPOSER TEST {datetime.datetime.utcnow():%d.%m %H%M}"
    shell["journeyName"] = name
    shell["activities"] = activities
    shell["reservedJourneyId"] = "DRY-RUN-COMMS"
    shell["isUnlimited"] = True             # comms journeys are unlimited (no dates)
    shell["isImmediatelyAfterPublish"] = True   # start on publish (no warning)
    shell["startAt"] = None
    shell["stopAt"] = None
    shell["isArchived"] = False
    shell["rawJourneyData"] = {
        "elements": elements,
        "infoValues": {
            "brand": shell.get("brand", BRAND),
            "startAt": None, "stopAt": None,
            "metadata": shell.get("metadata"),
            "timeZoneId": shell.get("timeZoneId", "Chile/Continental"),
            "isUnlimited": True,
            "journeyName": name,
            "reEntryRule": shell.get("reEntryRule"),
            "currencyCodes": shell.get("currencyCodes", ["CLP"]),
            "isImmediatelyAfterPublish": True,
        },
        "pathesConfiguration": {},
        "boundaryConfiguration": {},
        "exitCriteriaSettings": None,
        "activitiesConfiguration": acts_cfg,
    }
    return shell, name, chain_ids


def verify(body: dict) -> list[tuple[bool, str]]:
    acts = body["activities"]
    rjd = body["rawJourneyData"]
    ids = {a["activityId"] for a in acts}
    node_ids = {e["id"] for e in rjd["elements"] if e.get("type") in
                ("source", "action", "exit")}
    checks = []
    # every nextActivityId resolves
    dangling = []
    for a in acts:
        for ev in a.get("events", []) or []:
            nx = ev.get("nextActivityId")
            if nx and nx not in ids:
                dangling.append(nx)
    checks.append((not dangling, f"all nextActivityId resolve ({len(dangling)} dangling)"))
    # every non-terminal activity has a canvas node
    missing_node = [a["activityName"] for a in acts if a["activityId"] not in node_ids]
    checks.append((not missing_node, f"every activity has a canvas node (missing: {missing_node or 'none'})"))
    # every activitiesConfiguration key is a real activity
    bad_cfg = [k for k in rjd["activitiesConfiguration"] if k not in ids]
    checks.append((not bad_cfg, f"config keys all map to activities ({len(bad_cfg)} orphan)"))
    # every edge source/target is a node
    all_node_and_exit = node_ids
    bad_edge = []
    for e in rjd["elements"]:
        if e.get("type") in ("default", "emptyEdge"):
            if e.get("source") not in all_node_and_exit or e.get("target") not in all_node_and_exit:
                bad_edge.append(e.get("id"))
    checks.append((not bad_edge, f"every edge connects real nodes ({len(bad_edge)} bad)"))
    # chain reaches the terminal
    checks.append((any(a["activityName"] == "end_of_journey" for a in acts), "has an end_of_journey terminal"))
    # every node has position AND positionAbsolute with x/y (editor reads .x on both)
    bad_pos = []
    for e in rjd["elements"]:
        if e.get("type") in ("source", "action", "exit"):
            for key in ("position", "positionAbsolute"):
                p = e.get(key)
                if not isinstance(p, dict) or "x" not in p or "y" not in p:
                    bad_pos.append(f"{(e.get('data') or {}).get('name')}::{key}")
    checks.append((not bad_pos, f"every node has position + positionAbsolute ({bad_pos or 'none'})"))
    return checks


JS_TEMPLATE = r'''// Composed comms journey — CANVAS EXPERIMENT — generated @GENERATED_AT@
// Journey: @NAME@
//
// HOW TO RUN:
//   1. Open the Journey Builder backoffice in Chrome, logged in.
//   2. F12 -> Console (if warned, type: allow pasting).
//   3. Paste this whole script, Enter.
//   4. If it says "Waiting for a token", click anything in the backoffice.
//   5. Report back: did it create (JRN id + HTTP 201)? Does the draft OPEN in
//      the editor with the 5 nodes wired source->NC->NC->SMS->Email->end?
(async () => {
  const BASE = @BASE@;
  const BRAND = @BRAND@;
  const BODY = @BODY@;

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
  const headers=(ct)=>({ accept:'application/json, text/plain, */*', authorization:auth, 'content-type':ct, 'x-brand':BRAND });

  const newUuid=()=> (crypto&&crypto.randomUUID)? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,(c)=>{ const r=(Math.random()*16)|0; return (c==='x'?r:(r&0x3)|0x8).toString(16); });
  const UUID_RE=/"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  const regen=(txt)=>{ const olds=new Set(); let m; UUID_RE.lastIndex=0; while((m=UUID_RE.exec(txt))!==null) olds.add(m[1]); let t=txt; for(const o of olds) t=t.split(o).join(newUuid()); return t; };

  async function reserveId(){
    const r=await fetch(BASE+'/journeys/identifier',{ method:'POST', headers:headers('application/x-www-form-urlencoded'), credentials:'include' });
    const raw=(await r.text()).trim(); let id=raw.replace(/^"+|"+$/g,'');
    try{ const d=JSON.parse(raw); if(typeof d==='string') id=d.trim(); else if(d&&typeof d==='object') id=String(d.identifier||d.journeyId||d.id||d.value||'').trim(); }catch(e){}
    if(!r.ok||!id.startsWith('JRN-')) throw new Error('reserve failed HTTP '+r.status+' '+raw);
    return id;
  }

  console.log('Reserving journey id...');
  const rid = await reserveId();
  console.log('  reserved', rid);

  let text = JSON.stringify(BODY).split('DRY-RUN-COMMS').join(rid);
  text = regen(text);                    // fresh activity/port/handle ids per run
  const body = JSON.parse(text);

  console.log('Creating draft', rid, ':', body.journeyName);
  const r = await fetch(BASE+'/journey-drafts',{ method:'POST', headers:headers('application/json'), credentials:'include', body:JSON.stringify(body) });
  const respText = await r.text();
  if(!r.ok){ console.error('%cFAILED HTTP '+r.status,'color:#ef4444;font-weight:bold', respText); return; }
  console.log('%cDRAFT CREATED: '+rid,'color:#22c55e;font-weight:bold');
  console.log('Now open it in the editor and check the 5 nodes are wired. Response:', respText);
})();
'''


def emit(body: dict, name: str) -> Path:
    js = (JS_TEMPLATE
          .replace("@GENERATED_AT@", datetime.datetime.utcnow().isoformat() + "Z")
          .replace("@NAME@", name)
          .replace("@BASE@", json.dumps(BASE_URL))
          .replace("@BRAND@", json.dumps(BRAND))
          .replace("@BODY@", json.dumps(body, ensure_ascii=False)))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "comms_composed_console.js"
    out.write_text(js, encoding="utf-8")
    return out


def main() -> int:
    body, name, _ = build_body()
    checks = verify(body)
    print(f"Composed: {name}")
    print(f"  activities: {len(body['activities'])}  elements: {len(body['rawJourneyData']['elements'])}")
    ok = True
    for good, msg in checks:
        print(f"  [{'OK' if good else 'FAIL'}] {msg}")
        ok = ok and good
    if not ok:
        print("\nVerification FAILED — not emitting.")
        return 1
    out = emit(body, name)
    print(f"\nAll checks passed. Console script: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
