# test/test_app_js_cancel_optimize_confirm.py
"""Regressione: l'annullamento di un'ottimizzazione pagata chiede conferma e
dice dove finisce il rimborso.

Job LnRy1Zl12OCHOi2s46Sb7g (26/10/2026): `cancelOptimization()` mandava il
beacon `/api/cancel_optimize` al primo clic, un secondo dopo il pagamento
combinato. Il rimborso PayPal diventava un buono spedito per email, ma la
pagina diceva solo "ottimizzazione annullata" (in un nodo che la stessa
funzione nascondeva) e rimetteva il bottone di avvio: la cliente ha pagato una
seconda volta e ha visto due addebiti.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

NEW_KEYS = (
    "opt_cancel_confirm_title", "opt_cancel_confirm_body", "opt_cancel_confirm_no",
    "opt_cancel_refund_paypal", "opt_cancel_refund_voucher",
)


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    depth = 0
    i = APP.index("{", start)
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError("parentesi non bilanciate in %s" % name)


@pytest.mark.parametrize("key", NEW_KEYS)
def test_keys_translated_in_all_languages(key):
    assert I18N.count(key + ":") == 7, "chiave %s mancante in qualche lingua" % key


def test_cancel_does_not_fire_before_reading_the_payment():
    fn = _extract_fn("cancelOptimization")
    assert "sendBeacon" not in fn, \
        "il cancel non deve partire al primo clic: prima si legge il pagamento"
    assert "/api/cancel_preview/" in fn


FUNCTIONS = (
    "_tOr", "_mkCancelModal", "_cancelModalText", "_cancelModalChoice",
    "_cancelModalOk", "_optRefundText", "_confirmCancelOptModal",
    "_showOptCancelRefundModal", "_cancelOptimizationNow", "cancelOptimization",
)

JS_HARNESS = """
function mkEl(tag){
  return {tagName:tag,id:'',className:'',style:{},textContent:'',children:[],parent:null,listeners:{},
    appendChild(c){c.parent=this;this.children.push(c);return c},
    insertBefore(c,ref){c.parent=this;const i=this.children.indexOf(ref);
      this.children.splice(i<0?this.children.length:i,0,c);return c},
    remove(){if(this.parent){const a=this.parent.children;a.splice(a.indexOf(this),1);this.parent=null}},
    addEventListener(ev,fn){(this.listeners[ev]=this.listeners[ev]||[]).push(fn)},
    click(){(this.listeners.click||[]).forEach(fn=>fn({target:this}))}};
}
const body=mkEl('body');
function walk(el,fn){fn(el);el.children.forEach(c=>walk(c,fn))}
function findAll(root,pred){const out=[];walk(root,e=>{if(pred(e))out.push(e)});return out}
function textOf(root){return findAll(root,e=>e.tagName==='p').map(e=>e.textContent).join(' | ')}
globalThis.document={body,createElement:mkEl,
  getElementById:id=>findAll(body,e=>e.id===id)[0]||null};
globalThis.t=k=>k;
const calls=[],beacons=[];let resetCount=0,cfg={};
globalThis._resetAfterOptCancel=()=>{resetCount++};
// node >= 21 ha un `navigator` globale con solo getter: l'assegnazione cadrebbe nel vuoto.
Object.defineProperty(globalThis,'navigator',{configurable:true,
  value:{sendBeacon:u=>{beacons.push(u);return true}}});
globalThis.fetch=async(url,opts)=>{
  calls.push(((opts&&opts.method)||'GET')+' '+url);
  if(url.startsWith('/api/cancel_preview/')){
    if(cfg.previewFails) throw new Error('down');
    return {ok:true,json:async()=>cfg.preview};
  }
  if(url.startsWith('/api/cancel_optimize/')){
    if(cfg.cancelThrows) throw new Error('down');
    return {ok:cfg.cancelStatus===200,status:cfg.cancelStatus};
  }
  throw new Error('unexpected '+url);
};
async function flush(){for(let i=0;i<50;i++)await Promise.resolve()}
async function scenario(c){
  calls.length=0;beacons.length=0;resetCount=0;body.children.length=0;
  cfg=Object.assign({cancelStatus:200},c);
  if(c.payState) globalThis._payState=c.payState; else delete globalThis._payState;
  globalThis.jobId='J1';
  let ret='pending';
  cancelOptimization().then(v=>{ret=v});
  await flush();
  const confirm=document.getElementById('cancelOptConfirmModal');
  const out={confirmShown:!!confirm,confirmText:confirm?textOf(confirm):'',buttons:[],
    postsBeforeAnswer:calls.filter(x=>x.startsWith('POST')).length};
  if(confirm){
    const btns=findAll(confirm,e=>e.tagName==='button');
    out.buttons=btns.map(b=>b.textContent);
    btns[c.answer==='yes'?1:0].click();
    await flush();
  }
  const refund=document.getElementById('optCancelRefundModal');
  Object.assign(out,{ret,calls:calls.slice(),beacons:beacons.slice(),resetCount,
    confirmGone:!document.getElementById('cancelOptConfirmModal'),
    refundShown:!!refund,refundText:refund?textOf(refund):''});
  if(refund){
    findAll(refund,e=>e.tagName==='button')[0].click();
    out.refundClosed=!document.getElementById('optCancelRefundModal');
  }
  return out;
}
const SCENARIOS=%s;
(async()=>{
  const res={};
  for(const [name,c] of Object.entries(SCENARIOS)) res[name]=await scenario(c);
  process.stdout.write(JSON.stringify(res));
})();
"""

PAYPAL = {"paid_eur": 5.58, "paid_method": "paypal"}
SCENARIOS = {
    "paypal_no": {"preview": PAYPAL, "answer": "no"},
    "paypal_yes": {"preview": PAYPAL, "answer": "yes"},
    "voucher_yes": {"preview": {"paid_eur": 2, "paid_method": "voucher"}, "answer": "yes"},
    "free": {"preview": {"paid_eur": 0, "paid_method": None}},
    "already_synth": {"preview": PAYPAL, "answer": "yes", "cancelStatus": 404},
    "preview_down": {"previewFails": True, "payState": {"total": 3.1, "method": "paypal"},
                     "answer": "yes"},
    "post_down": {"preview": PAYPAL, "answer": "yes", "cancelThrows": True},
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node non disponibile")
    script = tmp_path_factory.mktemp("cancel_opt") / "check.js"
    script.write_text(
        "\n".join(_extract_fn(n) for n in FUNCTIONS)
        + JS_HARNESS % json.dumps(SCENARIOS),
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True,
                         encoding="utf-8")
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


CANCEL_POST = "POST /api/cancel_optimize/J1"


def test_paid_job_asks_before_cancelling(runs):
    r = runs["paypal_no"]
    assert r["confirmShown"], "su un job pagato serve la conferma"
    assert r["postsBeforeAnswer"] == 0, "il cancel e' partito prima della risposta"
    assert "5.58" in r["confirmText"] and "PayPal" in r["confirmText"]
    assert r["buttons"] == ["Continue", "Yes, cancel"]


def test_paid_job_kept_when_user_declines(runs):
    r = runs["paypal_no"]
    assert CANCEL_POST not in r["calls"] and not r["beacons"]
    assert r["resetCount"] == 0 and r["ret"] is False
    assert r["confirmGone"] and not r["refundShown"]


def test_paid_job_cancelled_shows_where_the_refund_goes(runs):
    r = runs["paypal_yes"]
    assert CANCEL_POST in r["calls"]
    assert r["resetCount"] == 1 and r["ret"] is True
    assert r["refundShown"], "dopo il cancel l'utente deve sapere del buono"
    assert "5.58" in r["refundText"] and "voucher" in r["refundText"]
    assert r["refundClosed"]


def test_voucher_payment_points_back_to_the_same_code(runs):
    r = runs["voucher_yes"]
    assert "2.00" in r["confirmText"]
    assert "goes back to your voucher" in r["refundText"]
    assert "PayPal" not in r["refundText"]


def test_unpaid_job_cancels_immediately(runs):
    r = runs["free"]
    assert not r["confirmShown"]
    assert CANCEL_POST in r["calls"] and r["resetCount"] == 1
    assert not r["refundShown"]


def test_no_reset_when_optimization_already_moved_on(runs):
    """404: l'ottimizzazione e' finita mentre la conferma era aperta."""
    r = runs["already_synth"]
    assert CANCEL_POST in r["calls"]
    assert r["resetCount"] == 0 and r["ret"] is False
    assert not r["refundShown"]


def test_payment_state_used_when_preview_unavailable(runs):
    r = runs["preview_down"]
    assert r["confirmShown"], "senza la preview vale l'importo del pagamento appena fatto"
    assert "3.10" in r["confirmText"]


def test_network_error_falls_back_to_beacon(runs):
    r = runs["post_down"]
    assert r["beacons"] == ["/api/cancel_optimize/J1"]
    assert r["resetCount"] == 1 and r["refundShown"]
