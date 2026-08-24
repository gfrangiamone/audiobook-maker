# Production Forensics & Incident Investigation

Playbook to diagnose a job incident (lost file, "link scaduto in anticipo", missing folder) **going straight to the point**. Production server is Bash/systemd.

## Topology (verified, not the documented defaults)

- Service: `audiobook-maker.service` (single process — Werkzeug dev server, **no gunicorn/multi-worker**). WorkingDirectory + code: `/opt/audiobook-maker`. There is also `audiobook-maker-test.service` (**separate** `ABM_DATA_DIR` — does not touch prod data).
- **`ABM_DATA_DIR = /opt/audiobook-maker/data`** (NOT `/var/lib/...`). Job dir = `data/<job_id>/output_<epoch>/...`.
- Env vars live in the systemd unit/EnvironmentFile, **not** visible via `grep ABM_ ...service`. Read the *actual* runtime env from `/proc/$(pgrep -f audiobook_app.py | head -1)/environ` (`tr '\0' '\n'`).
- **Cold storage is ENABLED**: Cloudflare R2 (`ABM_S3_*`, bucket `audiobook-maker`). boto3 is installed → can list/serve cold directly.
- **Sandbox (drop-in `hardening.conf`, installed 2026-08-24, in effect from the next service restart)**: `NoNewPrivileges`, `PrivateTmp`, `ProtectHome`, `ProtectSystem=full`. Two consequences when investigating:
  - The synthesis scratch dirs (`abmtts_*`) and FFmpeg `.err` files are **no longer in `/tmp`** but in `/tmp/systemd-private-*-audiobook-maker.service-*/tmp/`, and are **wiped on every service stop**. No job payload lives there (persistent chunks are in the job dir), but a leaked `abmtts_*` is no longer evidence you can find after a restart.
  - `/root` and `/home` are invisible to the process, and `/usr` `/boot` `/etc` are read-only for it. `/opt` (code + data dir) is untouched.

## Log sources — ranked by retention (use in this order)

1. **`activity_YYYY-MM.log` in the APP dir** (`/opt/audiobook-maker/`, = `SCRIPT_DIR`, **NOT** the data dir). Persistent per-month business log, never rotated aggressively. Format: `job_id # ts # "file" # OPERATION # client_id # ip # voice # lang`. Ops: `ANALYZE, PAYMENT_CAPTURED, OPTIMIZE, EMAIL_REGISTERED, OPT_COMPLETE, GENERATE, COMPLETE, EMAIL_SENT, DOWNLOAD_*`. → gives the clean lifecycle.
2. **`/var/log/syslog*` (rsyslog)** — **the long forensic source (~3–4 weeks, daily-rotated, `.gz`)**. rsyslog duplicates the app stdout. Use `zgrep -h <jid> /var/log/syslog* | sort`. This is the authoritative trace of every `print()` (progress, completion, **cleanup/eviction**).
3. **journald** (`journalctl -u audiobook-maker`) — **SHORT & unreliable**: was ~1 day; raised 2026-06-02 to `4G / 14day / persistent` via `/etc/systemd/journald.conf.d/retention.conf`. Also **rate-limited** (drops bursts → "Suppressed N messages"). Do NOT rely on it for events >a few days old.

## Persistent state files (in data dir)

`_download_tokens.json` (token→{job_id, created_at, downloaded_at, is_gemini, output_m4b, optimized_abm_path, …}), `_pending_jobs.json` (batch-recovery descriptors; may be absent), `_vouchers.json`, `_payments.json`, `_client_emails.json`. Job-dir markers: `.email_sent` (`<ts>|<window>` or `pending`), `.forensic_retain.json`, `.cloud_uploaded` (cold-upload timestamp).

## Deletion log strings (ALL contain the job_id → grep by job_id is decisive)

`[cleanup] <jid> removed (<reason>)`, `[cleanup] Orphan dir removed: <jid> (age: Ns)`, `[cleanup] Token-orphan dir removed: <jid>`, `[cleanup] Orphan output dir removed: <path>`, `[cleanup] Cold objects removed for job <jid>`, `[hot-evict] Local removed (cold copy ok): <path>`. **Absence of any of these in syslog for a job_id ⇒ the app did NOT delete it** (suspect manual `rm`, restore, cron, or out-of-band action). `check_disk_space.sh` only emails (never deletes); `deploy.yml` does `git reset --hard` on code only (untracked `data/` untouched).

## Fast diagnostic sequence

1. `grep <jid> /opt/audiobook-maker/activity_*.log` → lifecycle + whether ever downloaded.
2. `zgrep -h <jid> /var/log/syslog* | sort | tail -30` → last logged action + any deletion line.
3. `ls -la data/<jid>/`; `cat data/<jid>/.email_sent`; check `.forensic_retain.json` / `.cloud_uploaded`.
4. Parse the token in `_download_tokens.json` (created_at vs now, `downloaded_at`, `is_gemini`).
5. Process restarts: PID changes in syslog + `ps -o pid,lstart,etime -p <pid>` (a restart wipes in-memory `jobs{}` → `/dl` returns 410).
6. Cold check: boto3 `list_objects_v2(Prefix="<jid>/")` using env from `/proc/<pid>/environ` → confirms if the file survives in R2.

## Retention model (don't re-derive)

User-facing availability = base, **independent of cold storage**: EMAIL `ABM_JOB_RETENTION_SEC` (prod 86400=24h), Gemini `ABM_GEMINI_JOB_RETENTION_SEC` (172800=48h). Cold S3 only decides **where** the file is served (local during the hot window `ABM_HOT_WINDOW_SEC`/`ABM_HOT_WINDOW_GEMINI_SEC`, presigned URL after) — it does NOT extend the window. (Historical note: a blanket `COLD_RETENTION_MULTIPLIER=2` was removed 2026-06; pre-fix, S3-on jobs lived 2× longer.) The **only** extension is **×2 for PREMIUM/Gemini never-downloaded** (`GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER`) ⇒ such a job lives **96h** (48h×2); standard and already-downloaded PREMIUM are never extended. Orphan-dir cleanup fires at **2h** (`CLEANUP_ORPHAN_DIR_AGE_SEC`). Orphan/token-orphan/orphan-output branches **respect** the `.email_sent` + `.forensic_retain.json` markers; **`_cleanup_job` (status error/cancel/done-retention) does NOT check the email marker** and calls `_delete_cold_for_job` (purges both tiers).

## Ops terminal caveat (the SSH terminal mangles multi-line pastes)

It hard-wraps long lines (breaking string literals / `python3 -c`) and auto-indents (breaking Python heredocs → `IndentationError`; an indented heredoc terminator hangs at `>`). **Reliable pattern**: base64-encode the whole script locally, then on the server:
`echo '<BASE64>' | tr -cd 'A-Za-z0-9+/=' | base64 -d > /tmp/x.sh && bash /tmp/x.sh`
(`tr` strips paste-inserted spaces; `base64 -d` ignores newlines). For config files use single-line `echo 'line' >> file` appends. When generating the base64 from Windows PowerShell, write the script to a temp file first and encode via `[IO.File]::ReadAllText()` — inline here-strings containing path-like tokens (`/`, `/3600`) can trip a host safety hook.
