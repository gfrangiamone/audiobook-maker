"""Digest quotidiano VoxCPM: i ritentativi delle code tagliate, giorno per giorno.

Il worker verifica con l'ASR ogni chunk che consegna e rigenera quelli che
sente troncati (`handler.generate`, blocco `verify`). Finora l'esito di quel
lavoro finiva in un warning nel log del server e in un campo del libro
mastro che nessuno leggeva: chi gestisce il servizio non aveva modo di
sapere se la verifica stesse recuperando le code o solo spendendo GPU.

Questo modulo legge i record VoxCPM del libro mastro (`gemini_cost_audit`,
provider `voxcpm`) di UN giorno e ne ricava quattro numeri:

  necessari    ritentativi giudicati necessari dall'ASR (i «sospetti»)
  non tentati  necessari a cui il worker ha rinunciato perche' erano troppi
               (sopra VERIFY_MAX_FRAC rigenera solo i rotti conclamati)
  falliti      tentati e ancora difettosi alla consegna
  riusciti     tentati e tornati sani, per differenza

Nessuno dei numeri scritti nel record da' da solo la misura giusta:
`code_tagliate` conta i difettosi rimasti ma non distingue chi e' stato
tentato invano da chi non e' stato tentato affatto, e `sospetti` da solo non
dice quanti sono guariti. Il conto si chiude solo mettendoli insieme.

Il giorno e' quello UTC dei timestamp del libro mastro, non l'ora locale del
server: e' l'unico modo perche' due letture dello stesso giorno diano lo
stesso risultato.
"""
import os
from datetime import date, timedelta
from pathlib import Path

import gemini_cost_audit

# Il marker dell'ultimo giorno gia' riepilogato. Sta su disco e non in
# memoria perche' un riavvio del server non deve ne' saltare un giorno ne'
# rispedirlo: il digest arriva una volta sola per giorno, comunque vada il
# processo.
_DATA_DIR = Path(os.environ.get("ABM_DATA_DIR", "."))
_MARKER = "voxcpm_digest_last.txt"

# Quanti job elencare per esteso. Oltre, la mail diventa un tabulato che
# nessuno legge: il totale resta esatto, la coda si riassume in una riga.
MAX_RIGHE = 25


def _record_del_giorno(giorno):
    for rec in gemini_cost_audit.iter_records(date_from=giorno, date_to=giorno):
        if (rec.get("provider") or "") == "voxcpm":
            yield rec


def riepilogo(giorno):
    """I conti dei ritentativi di un giorno, dal libro mastro.

    Args:
        giorno: data ISO `YYYY-MM-DD`, in UTC come i timestamp dei record.

    Returns:
        dict coi totali del giorno e `job`, la lista per singolo job ordinata
        dai piu' difettosi. `job_totali` a zero significa che quel giorno
        VoxCPM non ha lavorato.
    """
    tot = {
        "giorno": giorno,
        "job_totali": 0,
        "job_con_difetti": 0,
        # Record scritti da una versione che non misurava ancora i
        # ritentativi: contano solo le code tagliate, e senza questo numero
        # un tasso di recupero calcolato su un giorno misto sarebbe falso.
        "job_senza_misure": 0,
        "chunk_verificati": 0,
        "necessari": 0,
        "non_tentati": 0,
        "tentati": 0,
        "riusciti": 0,
        "falliti": 0,
        "giri": 0,
        "code_tagliate": 0,
        # La regola dei numeri: `numerali` sono le code dove un numero
        # c'era, `falsi_numerali` quelle in cui il confronto sarebbe
        # scattato per la sola differenza di grafia — l'ASR scrive «1967»
        # dove il testo dice «millenovecentosessantasette». Sono ritentativi
        # non comprati, e il giorno in cui questo numero crolla a zero senza
        # motivo vuol dire che una lingua nuova e' passata sotto il naso
        # delle tabelle.
        "numerali": 0,
        "falsi_numerali": 0,
        # Job di un worker che misurava i ritentativi ma non ancora i
        # numeri: cieco solo su queste due colonne.
        "job_senza_numeri": 0,
        "job": [],
    }
    for rec in _record_del_giorno(giorno):
        tot["job_totali"] += 1
        tagliate = int(rec.get("worker_code_tagliate", 0) or 0)
        tot["code_tagliate"] += tagliate
        if "worker_verify_sospetti" not in rec:
            # Cieco: le code tagliate si contano lo stesso, i ritentativi no.
            tot["job_senza_misure"] += 1
            if tagliate:
                tot["job_con_difetti"] += 1
            continue
        necessari = int(rec.get("worker_verify_sospetti", 0) or 0)
        non_tentati = int(rec.get("worker_verify_rinunciati", 0) or 0)
        # Le code rimaste comprendono anche i rinunciati (il worker li
        # rimette nel conto a fine giro): togliendoli restano i tentativi
        # andati a vuoto.
        tentati = max(0, necessari - non_tentati)
        falliti = max(0, min(tentati, tagliate - non_tentati))
        riusciti = tentati - falliti
        tot["chunk_verificati"] += int(rec.get("worker_verify_chunks", 0) or 0)
        tot["necessari"] += necessari
        tot["non_tentati"] += non_tentati
        tot["tentati"] += tentati
        tot["riusciti"] += riusciti
        tot["falliti"] += falliti
        tot["giri"] += int(rec.get("worker_verify_giri", 0) or 0)
        if "worker_verify_numerali" in rec:
            tot["numerali"] += int(rec.get("worker_verify_numerali", 0) or 0)
            tot["falsi_numerali"] += int(
                rec.get("worker_verify_falsi_numerali", 0) or 0)
        else:
            tot["job_senza_numeri"] += 1
        if tagliate:
            tot["job_con_difetti"] += 1
        if necessari or tagliate:
            # In tabella vanno solo i job che qualcosa hanno avuto: un giorno
            # sano e' una tabella vuota, ed e' la lettura giusta.
            tot["job"].append({
                "job_id": rec.get("job_id", "") or "",
                "language": rec.get("language", "") or "—",
                "chars": int(rec.get("chars_total", 0) or 0),
                "necessari": necessari,
                "non_tentati": non_tentati,
                "riusciti": riusciti,
                "falliti": falliti,
                "giri": int(rec.get("worker_verify_giri", 0) or 0),
                "tagliate": tagliate,
            })
    tot["job"].sort(key=lambda j: (-j["tagliate"], -j["necessari"]))
    tot["tasso_recupero"] = (round(100.0 * tot["riusciti"] / tot["tentati"], 1)
                             if tot["tentati"] else None)
    return tot


# ---------------------------------------------------------------------------
# Il giorno da spedire
# ---------------------------------------------------------------------------

def _marker_path():
    return _DATA_DIR / _MARKER


def ultimo_inviato():
    """La data dell'ultimo giorno gia' riepilogato, o '' se non c'e'."""
    try:
        return _marker_path().read_text(encoding="utf-8").strip()[:10]
    except (OSError, ValueError):
        return ""


def segna_inviato(giorno):
    fp = _marker_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(giorno, encoding="utf-8")


def giorno_arretrato(oggi=None):
    """Il giorno da riepilogare adesso, o None se non c'e' nulla da spedire.

    Si riepiloga sempre IERI, mai oggi: un giorno ancora aperto darebbe conti
    parziali, e il digest del giorno dopo non potrebbe correggerli. Alla prima
    accensione non si spedisce l'arretrato di un mese: si prende soltanto
    ieri e si riparte da li'.
    """
    oggi = oggi or date.today()
    ieri = (oggi - timedelta(days=1)).isoformat()
    if ultimo_inviato() >= ieri:
        return None
    return ieri


# ---------------------------------------------------------------------------
# Il corpo della mail
# ---------------------------------------------------------------------------

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def oggetto(r):
    """L'oggetto dice l'esito, non il fatto che il digest esista."""
    if not r["job_totali"]:
        return "VoxCPM %s: nessuna generazione" % r["giorno"]
    rimaste = r["falliti"] + r["non_tentati"]
    if rimaste:
        return ("VoxCPM %s: %d code recuperate, %d rimaste"
                % (r["giorno"], r["riusciti"], rimaste))
    if r["necessari"]:
        return ("VoxCPM %s: %d code recuperate su %d"
                % (r["giorno"], r["riusciti"], r["necessari"]))
    return ("VoxCPM %s: %d job, nessuna coda tagliata"
            % (r["giorno"], r["job_totali"]))


def _riquadro(etichetta, valore, colore, nota):
    return (
        '<td style="padding:14px 10px;text-align:center;'
        'border-right:1px solid #eee">'
        '<div style="font-size:28px;font-weight:600;color:%s">%s</div>'
        '<div style="font-size:12px;color:#666;margin-top:4px">%s</div>'
        '<div style="font-size:11px;color:#999">%s</div></td>'
        % (colore, valore, etichetta, nota))


_TH = ('<th style="padding:10px 12px;text-align:%s;font-size:13px;'
       'color:#555">%s</th>')
_TD = 'padding:8px 12px;border-bottom:1px solid #eee'


def _tabella_job(r):
    righe = ""
    for j in r["job"][:MAX_RIGHE]:
        colore = "#c62828" if j["falliti"] else "#2e7d32"
        righe += (
            "<tr>"
            '<td style="%s;font-family:monospace;font-size:12px">%s</td>'
            '<td style="%s;font-size:13px">%s</td>'
            '<td style="%s;text-align:right;font-size:13px">%s</td>'
            '<td style="%s;text-align:center">%d</td>'
            '<td style="%s;text-align:center;color:#2e7d32">%d</td>'
            '<td style="%s;text-align:center;color:%s">%d</td>'
            '<td style="%s;text-align:center;color:#ef6c00">%d</td>'
            '<td style="%s;text-align:center;font-size:13px">%d</td>'
            "</tr>"
            % (_TD, _esc(j["job_id"][:12]), _TD, _esc(j["language"]),
               _TD, "{:,}".format(j["chars"]),
               _TD, j["necessari"], _TD, j["riusciti"],
               _TD, colore, j["falliti"], _TD, j["non_tentati"],
               _TD, j["giri"]))
    if not righe:
        righe = ('<tr><td colspan="8" style="padding:16px;color:#666;'
                 "text-align:center\">Nessun chunk sospetto: tutti i job sono "
                 "passati alla prima lettura.</td></tr>")
    resto = len(r["job"]) - MAX_RIGHE
    if resto > 0:
        righe += ('<tr><td colspan="8" style="padding:10px 12px;color:#888;'
                  'font-size:12px">… e altri %d job con difetti, non '
                  "elencati.</td></tr>" % resto)
    intestazione = (
        (_TH % ("left", "Job")) + (_TH % ("left", "Lingua"))
        + (_TH % ("right", "Caratteri")) + (_TH % ("center", "Necessari"))
        + (_TH % ("center", "Riusciti")) + (_TH % ("center", "Falliti"))
        + (_TH % ("center", "Non tentati")) + (_TH % ("center", "Giri")))
    return ('<table style="width:100%%;border-collapse:collapse;'
            'background:white;border:1px solid #ddd">'
            '<thead><tr style="background:#f0f5fa">%s</tr></thead>'
            "<tbody>%s</tbody></table>" % (intestazione, righe))


def html(r):
    """Il corpo HTML del digest a partire da `riepilogo`."""
    if not r["job_totali"]:
        return _pagina(r, '<p style="padding:20px;color:#666">Nessun job '
                          "VoxCPM registrato in questa giornata.</p>")

    tasso = ("—" if r["tasso_recupero"] is None
             else "%d%%" % round(r["tasso_recupero"]))
    riquadri = (
        _riquadro("ritentativi necessari", r["necessari"], "#1a3c5e",
                  "su %d chunk ascoltati" % r["chunk_verificati"])
        + _riquadro("riusciti", r["riusciti"], "#2e7d32",
                    "recupero %s" % tasso)
        + _riquadro("falliti", r["falliti"], "#c62828",
                    "%d giri di rigenerazione" % r["giri"])
        + _riquadro("non tentati", r["non_tentati"], "#ef6c00",
                    "oltre il tetto dei sospetti")
        + _riquadro("numeri riconosciuti", r["falsi_numerali"], "#6a4c93",
                    "su %d code con un numero" % r["numerali"]))

    numeri = ""
    if r["falsi_numerali"] or r["numerali"]:
        numeri = ('<p style="color:#555;font-size:13px;margin:10px 4px 0">'
                  "La regola dei numeri ha taciuto <strong>%d</strong> "
                  "allarmi su %d code che contenevano un numero: sono "
                  "ritentativi che nessuno ha comprato, perche' l'unica "
                  "differenza era la grafia (l'ASR scrive «1967» dove il "
                  "testo dice «millenovecentosessantasette»).</p>"
                  % (r["falsi_numerali"], r["numerali"]))
    if r["job_senza_numeri"]:
        numeri += ('<p style="color:#888;font-size:12px;margin:6px 4px 0">'
                   "%d job vengono da un worker precedente alla regola dei "
                   "numeri: i loro allarmi da grafia sono diventati "
                   "ritentativi veri.</p>" % r["job_senza_numeri"])

    ciechi = ""
    if r["job_senza_misure"]:
        ciechi = ('<p style="color:#888;font-size:12px;margin:12px 4px 0">'
                  "%d job su %d vengono da un worker che non misurava ancora "
                  "i ritentativi: le loro code tagliate sono nel totale, i "
                  "loro tentativi no.</p>"
                  % (r["job_senza_misure"], r["job_totali"]))

    corpo = (
        '<table style="width:100%;border-collapse:collapse;background:white;'
        'border:1px solid #ddd;border-top:none"><tr>' + riquadri
        + "</tr></table>"
        '<p style="color:#555;font-size:13px;margin:16px 4px 6px">'
        "<strong>%d</strong> job VoxCPM, di cui <strong>%d</strong> consegnati "
        "con almeno una coda ancora tagliata (<strong>%d</strong> chunk in "
        "tutto).</p>" % (r["job_totali"], r["job_con_difetti"],
                         r["code_tagliate"])
        + _tabella_job(r) + numeri + ciechi)
    return _pagina(r, corpo)


def _pagina(r, corpo):
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="font-family:system-ui,-apple-system,sans-serif;'
        'color:#333;max-width:900px;margin:0 auto;padding:20px">'
        '<div style="background:linear-gradient(135deg,#1a3c5e,#2c5f8a);'
        'color:white;padding:20px 24px;border-radius:12px 12px 0 0">'
        '<h2 style="margin:0">\U0001f50a VoxCPM — code tagliate del '
        "%s</h2>"
        '<p style="margin:8px 0 0;opacity:.85">Ritentativi della verifica ASR '
        "sul worker — giornata UTC</p></div>%s"
        '<p style="color:#999;font-size:12px;margin-top:16px;padding:0 4px">'
        "Un chunk è <em>sospetto</em> quando l'ASR del worker sente la "
        "frase finire prima del suo testo. Il worker lo rigenera con un altro "
        "seme, per al massimo ABM_VOXCPM_VERIFY_TRIES giri, e tiene il nuovo "
        "take solo se è migliore del vecchio. Quando i sospetti superano "
        "ABM_VOXCPM_VERIFY_MAX_FRAC rigenera soltanto i rotti conclamati: gli "
        "altri restano fra i «non tentati». L'audio viene "
        "consegnato in ogni caso. Prima di confrontare, il worker riduce a un "
        "segno unico i numeri di entrambe le code — cifre, lettere e simboli "
        "— perché altrimenti «1967» e «millenovecentosessantasette» "
        "sembrerebbero una coda mancante: quelle sono le code contate fra i "
        "«numeri riconosciuti».</p>"
        '<p style="color:#999;font-size:12px;padding:0 4px">Messaggio '
        "automatico di Audiobook Maker. Per disattivarlo: ABM_VOXCPM_DIGEST=0 "
        "nella configurazione del server.</p></body></html>"
        % (_esc(r["giorno"]), corpo))
