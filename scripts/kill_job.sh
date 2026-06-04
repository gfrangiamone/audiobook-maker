#!/usr/bin/env bash
# =============================================================================
# kill_job.sh — Uccide DEFINITIVAMENTE un job Audiobook Maker (PROD)
# -----------------------------------------------------------------------------
# Sequenza:
#   1. STOP del job se in corso (POST /api/cancel o /api/cancel_optimize con
#      X-Admin-Token; refund automatico gestito dall'app per i job pagati),
#      poi attesa che il thread smetta di scrivere file.
#   2. Cancella la cartella locale del job (tier HOT): $ABM_DATA_DIR/<job_id>/
#   3. Cancella tutti gli oggetti cold su S3/R2 (tier COLD): prefisso "<job_id>/"
#
# NON tocca: token in _download_tokens.json (l'orphan-cleanup li scartera'),
# activity log, payments/vouchers.
#
# Uso:   bash kill_job.sh <job_id>
# Es.:   bash kill_job.sh f_K62B4o5MLnle5aWSRyUg
#
# IRREVERSIBILE: chiede conferma esplicita (digitare il job_id) prima di agire.
# =============================================================================
set -uo pipefail

JID="${1:-}"
if [ -z "$JID" ]; then
  echo "Uso: $0 <job_id>"
  exit 1
fi
# Sanity: niente path traversal / job_id vuoti o sospetti
case "$JID" in
  *[/\\]*|.|..|"")
    echo "ERRORE: job_id non valido: '$JID'"
    exit 1
    ;;
esac

APP_DIR="/opt/audiobook-maker"

sep() { printf '\n========== %s ==========\n' "$1"; }

# -----------------------------------------------------------------------------
# 0. Env reale dal /proc del processo app (ABM_DATA_DIR, ABM_S3_*)
# -----------------------------------------------------------------------------
PID="$(pgrep -f audiobook_app.py | head -1)"
ENVFILE=""
[ -n "${PID:-}" ] && ENVFILE="/proc/$PID/environ"

getenv() { # getenv VAR DEFAULT
  local var="$1" def="${2:-}"
  if [ -n "$ENVFILE" ] && [ -r "$ENVFILE" ]; then
    local v
    v="$(tr '\0' '\n' < "$ENVFILE" | grep -m1 "^${var}=" | cut -d= -f2-)"
    if [ -n "$v" ]; then echo "$v"; return; fi
  fi
  echo "$def"
}

DATA_DIR="$(getenv ABM_DATA_DIR "$APP_DIR/data")"
JOB_DIR="$DATA_DIR/$JID"

S3_ENDPOINT="$(getenv ABM_S3_ENDPOINT "")"
S3_BUCKET="$(getenv ABM_S3_BUCKET "")"
S3_AKEY="$(getenv ABM_S3_ACCESS_KEY "")"
S3_SKEY="$(getenv ABM_S3_SECRET_KEY "")"
S3_PREFIX="$(getenv ABM_S3_KEY_PREFIX "")"
S3_PREFIX="${S3_PREFIX#/}"; S3_PREFIX="${S3_PREFIX%/}"
COLD_PREFIX="${S3_PREFIX:+$S3_PREFIX/}$JID/"
S3_OK=0
[ -n "$S3_ENDPOINT" ] && [ -n "$S3_BUCKET" ] && [ -n "$S3_AKEY" ] && [ -n "$S3_SKEY" ] && S3_OK=1

# -----------------------------------------------------------------------------
# 1. Inventario: cosa verra' cancellato (HOT + COLD)
# -----------------------------------------------------------------------------
sep "INVENTARIO JOB $JID"

HOT_FOUND=0
if [ -d "$JOB_DIR" ]; then
  HOT_FOUND=1
  echo "[HOT]  $JOB_DIR"
  du -sh "$JOB_DIR" 2>/dev/null
  find "$JOB_DIR" -type f -printf '       %10s  %p\n' 2>/dev/null | sort -k2
else
  echo "[HOT]  cartella locale assente: $JOB_DIR"
fi

COLD_COUNT=0
if [ "$S3_OK" = "1" ]; then
  export KJ_ENDPOINT="$S3_ENDPOINT" KJ_BUCKET="$S3_BUCKET" \
         KJ_AKEY="$S3_AKEY" KJ_SKEY="$S3_SKEY" KJ_PREFIX="$COLD_PREFIX"
  COLD_COUNT="$(python3 - <<'PY'
import os, sys
try:
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["KJ_ENDPOINT"],
                      aws_access_key_id=os.environ["KJ_AKEY"],
                      aws_secret_access_key=os.environ["KJ_SKEY"])
    n = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=os.environ["KJ_BUCKET"],
                                   Prefix=os.environ["KJ_PREFIX"]):
        for obj in page.get("Contents", []):
            n += 1
            print(f"       {obj['Size']:>10}  s3://{os.environ['KJ_BUCKET']}/{obj['Key']}",
                  file=sys.stderr)
    print(n)
except Exception as e:
    print(f"       WARN: list cold fallita: {e}", file=sys.stderr)
    print(-1)
PY
)"
  if [ "$COLD_COUNT" = "-1" ]; then
    echo "[COLD] ERRORE nel listare gli oggetti cold (vedi sopra)."
  elif [ "$COLD_COUNT" = "0" ]; then
    echo "[COLD] nessun oggetto su s3://$S3_BUCKET/$COLD_PREFIX"
  else
    echo "[COLD] $COLD_COUNT oggetti su s3://$S3_BUCKET/$COLD_PREFIX (elencati sopra)"
  fi
else
  echo "[COLD] backend S3 non configurato (nessun tier cold da cancellare)"
fi

if [ "$HOT_FOUND" = "0" ] && { [ "$S3_OK" = "0" ] || [ "$COLD_COUNT" = "0" ]; }; then
  echo
  echo "Niente da cancellare per il job $JID. Esco."
  exit 0
fi

# -----------------------------------------------------------------------------
# 2. Avviso + conferma esplicita
# -----------------------------------------------------------------------------
sep "ATTENZIONE — OPERAZIONE IRREVERSIBILE"

# Job ancora attivo? (file modificati negli ultimi 120s -> l'app sta scrivendo:
# rm -rf perderebbe la corsa con le nuove scritture)
ACTIVE=0
if [ "$HOT_FOUND" = "1" ]; then
  RECENT="$(find "$JOB_DIR" -type f -newermt '-120 seconds' 2>/dev/null | head -3)"
  if [ -n "$RECENT" ]; then
    ACTIVE=1
    echo "*** IL JOB SEMBRA ANCORA ATTIVO: file scritti negli ultimi 120s ***"
    echo "$RECENT" | sed 's/^/      /'
    echo "*** L'app continuera' a ricreare file: cancellazione inaffidabile."
    echo "*** Consigliato: cancellare il job dalla UI/admin o attendere che termini."
    echo
  fi
fi
cat <<EOF
Stai per UCCIDERE DEFINITIVAMENTE il job $JID:
  1. STOP del job se in corso (cancel via API admin: generazione/ottimizzazione)
  2. tier HOT  : intera cartella $JOB_DIR (audio, .abm, marker)
  3. tier COLD : tutti gli oggetti S3/R2 sotto "$COLD_PREFIX"

Conseguenze:
  - se il job era PAGATO e in corso, il cancel innesca il REFUND automatico
    (riaccredito voucher / voucher bonus per PayPal)
  - i link /dl/<token> del job smetteranno di funzionare (410/404)
  - NESSUN recupero possibile: non esiste backup oltre questi due tier
  - eventuali marker di protezione (.email_sent, .forensic_retain.json)
    vengono IGNORATI e cancellati insieme alla cartella
EOF
echo
printf 'Per confermare digita il job_id (%s), qualsiasi altro input annulla: ' "$JID"
read -r CONFIRM
if [ "$CONFIRM" != "$JID" ]; then
  echo "Annullato. Nessuna modifica."
  exit 1
fi

# -----------------------------------------------------------------------------
# 3. STOP del job in-app (cancel via API admin) — PRIMA di toccare lo storage.
#    Senza questo, il thread di generazione/ottimizzazione continua a scrivere
#    e rm -rf perde la corsa (e il cold puo' essere ri-popolato dall'offload).
# -----------------------------------------------------------------------------
sep "STOP JOB IN-APP"
ADMIN_TOKEN="$(getenv ABM_ADMIN_TOKEN "")"
PORT="$(getenv ABM_PORT "5601")"
BASE="http://127.0.0.1:$PORT"

# Check refund pregresso: se _vouchers.json contiene gia' una traccia di refund
# per questo job (riaccredito voucher o voucher di rimborso PayPal), il cancel
# NON deve rigenerarlo. L'enforcement e' lato app (payment.has_refund_for_job,
# guard persistente in _refund_job_payment/_refund_gemini_payment); qui lo si
# rileva e segnala all'operatore.
export KJ_JID="$JID" KJ_VFILE="$DATA_DIR/_vouchers.json"
python3 - <<'PY'
import json, os
jid, vfile = os.environ["KJ_JID"], os.environ["KJ_VFILE"]
try:
    vouchers = json.load(open(vfile, encoding="utf-8"))
except FileNotFoundError:
    print("Refund pregresso: _vouchers.json assente -> nessun refund tracciato.")
    raise SystemExit(0)
except Exception as e:
    print(f"WARN: lettura {vfile} fallita ({e}): check refund non eseguibile.")
    raise SystemExit(0)
found = []
for code, v in (vouchers or {}).items():
    if v.get("kind") == "refund" and v.get("origin_job_id") == jid:
        found.append(f"voucher di rimborso {code} (kind=refund, {v.get('amount_eur', 0):.2f} EUR)")
    for u in (v.get("uses") or []):
        try:
            amt = float(u.get("amount_eur", 0) or 0)
        except (TypeError, ValueError):
            continue
        if u.get("job_id") == jid and amt < 0:
            found.append(f"riaccredito {-amt:.2f} EUR sul voucher {code}")
if found:
    print("*** REFUND GIA' EFFETTUATO in precedenza per questo job: ***")
    for f in found:
        print(f"      - {f}")
    print("*** Il cancel NON deve rigenerarlo: l'app lo salta (guard persistente")
    print("*** has_refund_for_job). Verificare nei log 'Refund skipped'.")
else:
    print("Refund pregresso: nessuna traccia in _vouchers.json.")
PY

json_field() { # json_field <campo>  (stdin: JSON) -> valore o stringa vuota
  python3 -c 'import json,sys
try: print(json.load(sys.stdin).get(sys.argv[1], "") or "")
except Exception: print("")' "$1" 2>/dev/null
}

JOB_RUNNING=0
CANCEL_REFUSED=0
if [ -z "$ADMIN_TOKEN" ]; then
  echo "WARN: ABM_ADMIN_TOKEN assente nell'env del processo: impossibile chiamare"
  echo "      le API di cancel. Se il job e' attivo, la cancellazione storage"
  echo "      sara' inaffidabile."
elif [ -z "${PID:-}" ]; then
  echo "App non in esecuzione: nessun job da fermare."
else
  ST="$(curl -s -m 10 -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE/api/job_status/$JID" | json_field status)"
  echo "Stato job in-app: ${ST:-(non presente in jobs{})}"
  case "$ST" in
    optimizing)
      JOB_RUNNING=1
      R="$(curl -s -m 10 -X POST -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE/api/cancel_optimize/$JID")"
      echo "cancel_optimize -> $R"
      ;;
    generating|analyzed|optimized)
      # 'generating' = TTS in corso; gli altri stati possono avere thread/recovery
      # pendenti: il cancel e' comunque innocuo (setta solo il flag).
      [ "$ST" = "generating" ] && JOB_RUNNING=1
      R="$(curl -s -m 10 -X POST -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE/api/cancel/$JID?force=1")"
      echo "cancel (force=1) -> $R"
      case "$R" in *cancel_locked_progress*)
        CANCEL_REFUSED=1
        echo "ERRORE: cancel rifiutato (lock Gemini oltre soglia). Il thread e' ANCORA VIVO."
        echo "        App aggiornata: force=1 + X-Admin-Token bypassa il lock — questa"
        echo "        risposta indica che il fix non e' ancora deployato."
        ;;
      esac
      ;;
    ""|not_found)
      echo "Job non presente in memoria: nessun thread da fermare."
      ;;
    *)
      echo "Stato '$ST': nessun cancel necessario."
      ;;
  esac
fi

if [ "$CANCEL_REFUSED" = "1" ]; then
  echo
  echo "Cancellare lo storage con il thread vivo lascia il job 'in esecuzione' nella"
  echo "console admin e fara' fallire il job con errori FileNotFound (con possibile"
  echo "refund duplicato se il guard persistente non e' deployato)."
  printf "Procedere COMUNQUE con la cancellazione storage? Digita PROCEDI: "
  read -r GO
  if [ "$GO" != "PROCEDI" ]; then
    echo "Annullato. Storage non toccato."
    exit 1
  fi
fi

# Attende che il thread molli la presa: nessun file scritto negli ultimi 30s
# (il flag cancelled viene controllato per-chunk; una chiamata TTS in volo puo'
# durare decine di secondi senza scrivere nulla — 10s davano falsi negativi).
if [ "$HOT_FOUND" = "1" ] && [ -d "$JOB_DIR" ] && { [ "$JOB_RUNNING" = "1" ] || [ "$ACTIVE" = "1" ]; }; then
  echo "Attendo che il job smetta di scrivere (quiescenza 30s, max 180s)..."
  WAITED=0
  while [ "$WAITED" -lt 180 ]; do
    BUSY="$(find "$JOB_DIR" -type f -newermt '-30 seconds' 2>/dev/null | head -1)"
    [ -z "$BUSY" ] && break
    sleep 5
    WAITED=$((WAITED + 5))
  done
  if [ "$WAITED" -ge 180 ]; then
    echo "WARN: il job scrive ancora dopo 180s. La cancellazione storage puo' fallire"
    echo "      o essere parziale; il cold puo' essere ri-popolato dall'offload."
    printf "Procedere comunque? Digita PROCEDI per continuare, altro per annullare: "
    read -r GO
    if [ "$GO" != "PROCEDI" ]; then
      echo "Annullato. Storage non toccato (il cancel in-app resta inviato)."
      exit 1
    fi
  else
    echo "Job fermo (nessuna scrittura da 10s, attesa: ${WAITED}s)."
  fi
fi

# -----------------------------------------------------------------------------
# 4. Cancellazione HOT (con retry: l'app puo' ricreare file durante l'rm)
# -----------------------------------------------------------------------------
sep "CANCELLAZIONE"
HOT_FAIL=0
if [ "$HOT_FOUND" = "1" ]; then
  for attempt in 1 2 3 4 5; do
    rm -rf -- "$JOB_DIR" 2>/dev/null
    [ ! -d "$JOB_DIR" ] && break
    echo "[HOT]  tentativo $attempt: cartella ricreata/non vuota, riprovo..."
    sleep 2
  done
  if [ -d "$JOB_DIR" ]; then
    HOT_FAIL=1
    echo "[HOT]  ERRORE: cartella ancora presente dopo 5 tentativi: $JOB_DIR"
    echo "[HOT]  Contenuto residuo (l'app sta probabilmente ancora scrivendo):"
    find "$JOB_DIR" -type f 2>/dev/null | head -10 | sed 's/^/       /'
  else
    echo "[HOT]  cancellata: $JOB_DIR"
  fi
else
  echo "[HOT]  niente da cancellare"
fi

# -----------------------------------------------------------------------------
# 5. Cancellazione COLD (batch da 1000, come storage_backend.delete_prefix)
# -----------------------------------------------------------------------------
COLD_FAIL=0
if [ "$S3_OK" = "1" ] && [ "$COLD_COUNT" != "0" ]; then
  python3 - <<'PY' || COLD_FAIL=1
import os, sys
try:
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["KJ_ENDPOINT"],
                      aws_access_key_id=os.environ["KJ_AKEY"],
                      aws_secret_access_key=os.environ["KJ_SKEY"])
    bucket, prefix = os.environ["KJ_BUCKET"], os.environ["KJ_PREFIX"]
    paginator = s3.get_paginator("list_objects_v2")
    batch, n = [], 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            batch.append({"Key": obj["Key"]})
            n += 1
            if len(batch) == 1000:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
                batch = []
    if batch:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
    # verifica post-delete
    left = s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("KeyCount", 0)
    if left:
        print(f"[COLD] ERRORE: {left} oggetti ancora presenti sotto {prefix}")
        sys.exit(1)
    print(f"[COLD] cancellati {n} oggetti sotto s3://{bucket}/{prefix}")
except SystemExit:
    raise
except Exception as e:
    print(f"[COLD] ERRORE delete: {e}")
    sys.exit(1)
PY
elif [ "$S3_OK" = "1" ]; then
  echo "[COLD] niente da cancellare"
fi

sep "ESITO"
if [ "$HOT_FAIL" = "1" ] || [ "$COLD_FAIL" = "1" ]; then
  [ "$HOT_FAIL" = "1" ] && echo "HOT : NON eliminato completamente ($JOB_DIR)"
  [ "$COLD_FAIL" = "1" ] && echo "COLD: errore nella cancellazione (vedi sopra)"
  echo
  echo "ATTENZIONE: se il job e' ancora in esecuzione nell'app, questo script NON"
  echo "puo' fermarlo (cancella solo lo storage). Il thread continuera' a scrivere"
  echo "file e puo' ri-popolare anche il tier cold. Fermare prima il job (cancel"
  echo "dall'app) o riavviare il servizio, poi rilanciare questo script."
  exit 1
fi
echo "Job $JID eliminato (hot+cold). Traccia nei log: questa azione e' OUT-OF-BAND"
echo "rispetto all'app (nessuna riga [cleanup] in syslog per questa cancellazione)."
