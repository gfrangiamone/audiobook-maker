# test/test_app_js_voxcpm_clip_icons.py
"""Regressione: cambiando voce, i bottoni delle clip devono tornare su "play".

Difetto osservato nel collaudo (modello VOXCPM2, pagina di scelta della voce):
con una clip in riproduzione si cambia voce, l'audio smette — ma i due bottoni
restano con l'icona di pausa, come se stessero ancora suonando.

La causa non e' una pause() mancante: `_loadVoxcpmSample` la fa. E' che subito
dopo cambia la sorgente del player, e il caricamento di una nuova sorgente
svuota la coda degli eventi del media element (media load algorithm, punto 4):
l'evento 'pause' appena accodato viene rimosso prima di essere consegnato, e
l'unico codice che aggiornava l'icona era in ascolto proprio di quell'evento.
Le icone vanno percio' risincronizzate esplicitamente dopo ogni ricarica.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")


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


def _extract_clips():
    m = re.search(r"const _VOXCPM_CLIPS=\[.*?\];", APP, re.S)
    assert m, "lista _VOXCPM_CLIPS non trovata"
    return m.group(0)


# Un player che si comporta come quello vero sui due punti che contano: pause()
# accoda l'evento invece di consegnarlo subito, e cambiare sorgente svuota la
# coda. Senza questa seconda parte il difetto non e' riproducibile.
FINTO_DOM = """
class FintoAudio{
  constructor(){this._src='';this.paused=true;this.ended=false;this.coda=[];this.ascolto={};}
  addEventListener(ev,fn){(this.ascolto[ev]=this.ascolto[ev]||[]).push(fn);}
  get src(){return this._src;}
  set src(v){this._src=v;this.coda=[];}                 // il caricamento svuota la coda
  getAttribute(){return this._src||null;}
  removeAttribute(){this._src='';this.coda=[];}
  load(){this.coda=[];this.paused=true;}
  pause(){if(!this.paused){this.paused=true;this.coda.push('pause');}}
  suona(){this.paused=false;this.ended=false;this.coda.push('play');}
  consegna(){const c=this.coda;this.coda=[];for(const ev of c)for(const fn of (this.ascolto[ev]||[]))fn();}
}
function fintoBottone(){
  const ico={textContent:'\\u25B6'};
  return {dataset:{},hidden:false,querySelector:()=>ico,ico};
}
const NODI={};
for(const [btnId,audioId] of _VOXCPM_CLIPS){NODI[btnId]=fintoBottone();NODI[audioId]=new FintoAudio();}
for(const id of ['voxcpmDemoBlock','voxcpmSampleBlock'])NODI[id]={hidden:false};
globalThis.document={getElementById:id=>NODI[id]||null};
globalThis._wireVoxcpmListen=()=>{};
globalThis._applyVoxcpmListenParams=()=>{};
let VOCE=null;
globalThis._voxcpmSelectedVoice=()=>VOCE;
const stato=()=>_VOXCPM_CLIPS.map(([btnId])=>NODI[btnId].ico.textContent);
const playing=()=>_VOXCPM_CLIPS.map(([btnId])=>NODI[btnId].dataset.playing||'');
"""

CODICE = "\n".join([_extract_clips(), _extract_fn("_syncVoxcpmClipIcons"),
                    _extract_fn("_loadVoxcpmSample"), _extract_fn("_pauseVoxcpmSample")])


def _esegui(tmp_path, nome, corpo):
    script = tmp_path / nome
    script.write_text(CODICE + FINTO_DOM + corpo, encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip())


PAUSA, PLAY = "⏸", "▶"

DUE_CLIP = """
VOCE={demos:[{common:true,url:'/a-comune.wav'},{common:false,url:'/a-adatta.wav'}]};
_loadVoxcpmSample();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_cambio_voce_riporta_i_bottoni_su_play(tmp_path):
    """Il caso del collaudo: clip in riproduzione, si cambia voce."""
    got = _esegui(tmp_path, "cambio.js", DUE_CLIP + """
NODI.voxcpmDemoCommon.suona();NODI.voxcpmDemoCommon.consegna();_syncVoxcpmClipIcons();
const prima=stato();
VOCE={demos:[{common:true,url:'/b-comune.wav'},{common:false,url:'/b-adatta.wav'}]};
_loadVoxcpmSample();
for(const [,audioId] of _VOXCPM_CLIPS)NODI[audioId].consegna();
console.log(JSON.stringify({prima,dopo:stato(),playing:playing()}));
""")
    assert got["prima"][0] == PAUSA, "la clip in riproduzione deve mostrare la pausa"
    assert got["dopo"] == [PLAY, PLAY, PLAY], "icone rimaste sulla pausa dopo il cambio voce"
    assert got["playing"] == ["", "", ""]


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_cambio_verso_una_voce_senza_clip_adatta(tmp_path):
    """La voce nuova ha la sola frase comune: nessuno dei due bottoni resta acceso."""
    got = _esegui(tmp_path, "senza_adatta.js", DUE_CLIP + """
NODI.voxcpmDemoStyled.suona();NODI.voxcpmDemoStyled.consegna();_syncVoxcpmClipIcons();
const prima=stato();
VOCE={demos:[{common:true,url:'/b-comune.wav'}]};
_loadVoxcpmSample();
for(const [,audioId] of _VOXCPM_CLIPS)NODI[audioId].consegna();
console.log(JSON.stringify({prima,dopo:stato()}));
""")
    assert got["prima"][1] == PAUSA
    assert got["dopo"] == [PLAY, PLAY, PLAY]


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_uscendo_da_voxcpm_i_bottoni_non_restano_accesi(tmp_path):
    """Cambio modello o cambio tab: _pauseVoxcpmSample svuota i player e le icone."""
    got = _esegui(tmp_path, "uscita.js", DUE_CLIP + """
NODI.voxcpmDemoCommon.suona();NODI.voxcpmDemoCommon.consegna();_syncVoxcpmClipIcons();
const prima=stato();
_pauseVoxcpmSample();
for(const [,audioId] of _VOXCPM_CLIPS)NODI[audioId].consegna();
console.log(JSON.stringify({prima,dopo:stato()}));
""")
    assert got["prima"][0] == PAUSA
    assert got["dopo"] == [PLAY, PLAY, PLAY]


def test_il_cablaggio_usa_la_stessa_risincronizzazione():
    """Un aggiornamento icona che vive solo dentro il cablaggio tornerebbe cieco."""
    fn = _extract_fn("_wireVoxcpmListen")
    assert "_syncVoxcpmClipIcons" in fn, \
        "gli eventi del player devono passare dalla risincronizzazione comune"
    assert "const aggiorna=" not in fn, "aggiornamento icona duplicato dentro il cablaggio"


def test_le_due_liste_delle_clip_sono_una_sola():
    """Bottoni e player appaiati: due liste separate si scollano al primo ritocco."""
    assert "const _VOXCPM_AUDIO_IDS=_VOXCPM_CLIPS.map(" in APP
    for btn_id in ("voxcpmDemoCommonBtn", "voxcpmDemoStyledBtn", "voxcpmSampleBtn"):
        assert APP.count("'%s'" % btn_id) >= 1, "bottone %s fuori dalla lista" % btn_id
