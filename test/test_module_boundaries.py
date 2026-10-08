"""Guardia automatica di md_files/REGOLE_CODICE.md (§2 confini, §11.4 pattern).

Tre controlli:
1. Le foglie dichiarate importano solo stdlib, dipendenze pip o altre foglie.
2. Nessun modulo importa `audiobook_app`.
3. I pattern vietati (env inline, retry a mano, client LLM, letture ffmpeg
   fuori da audio_utils, HTML nei .py, ...) hanno un conteggio per file che
   puo' solo SCENDERE rispetto a `test/boundaries_baseline.json`.

Aggiornare la baseline (solo in diminuzione) con:
    python test/test_module_boundaries.py
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).with_name("boundaries_baseline.json")

# REGOLE_CODICE.md §2.2
LEAVES = {
    "voice_utils", "cost_carry", "db", "load_metrics", "storage_tiering",
    "semantic_judge", "secure_archive", "text_reflow", "gemini_transport",
    "gemini_availability", "chunk_reuse", "assembly_queue", "cancel_policy",
    "activity_log", "activity_db", "user_stats", "env_utils", "fileio",
    "client_identity", "ratelimit", "content_store", "i18n", "page_brand", "seo_ld", "email_layout",
}

# Moduli di servizio che non devono importare generation_engine (§2.1).
SERVICES_NO_ENGINE = {
    "section_judge", "translation_judge", "transcript_judge",
    "llm_output_judge", "voice_language_guard", "community_moderator",
    "community_translator", "abuse_watch", "free_quota", "free_tts_quota",
    "community_store", "pending_jobs", "metrics_store", "email_service",
    "accounts", "payment", "voice_clone", "voxcpm_ranking",
}

# (nome, regex, moduli in cui il pattern e' ammesso)
PATTERNS = [
    ("env_inline", r"os\.environ\.get\(", {"env_utils"}),
    ("env_helper_def", r"def _env(_int|_float|_bool|_str|_num)?\(|def _f\(|def _i\(|def _b\(|def _f_env\(", {"env_utils"}),
    ("atomic_write_by_hand", r"os\.replace\(", {"fileio"}),
    ("retry_loop_by_hand", r"for _?attempt in range\(", {"retry_util"}),
    ("llm_call_by_hand", r"chat\.completions\.create\(", {"llm_client"}),
    ("import_generation_engine", r"^\s*(import generation_engine|from generation_engine import)", set()),
    ("voice_prefix_literal", r'"(voxcpm:mine:|gemini:|speechify:)"', {"voice_utils"}),
    ("ffmpeg_outside_audio_utils", r'["\']ff(mpeg|probe)["\']', {"audio_utils"}),
    ("forwarded_for_by_hand", r'headers\.get\(\s*["\']X-Forwarded-For', set()),
    ("lang_split_by_hand", r'\.split\("-"\)\[0\]\.lower\(\)', {"i18n"}),
    ("html_doctype_in_py", r"<!DOCTYPE html", {"email_layout"}),   # le email sono documenti interi
    ("naive_utc", r"\.utcnow\(\)|\.utcfromtimestamp\(", set()),
    ("mirror_comment", r"(?i)(mirror (del|of)|clone di|identica a .* salvo)", set()),
]


def _project_modules():
    mods = {p.stem for p in ROOT.glob("*.py")}
    mods |= {"templates"}
    return mods


def _imports(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            out.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out


def _scan_files():
    files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "templates").glob("*.py"))
    return [p for p in files if p.name != "version.py"]


def compute_counts():
    counts = {}
    for p in _scan_files():
        mod = p.stem
        src = p.read_text(encoding="utf-8", errors="replace")
        for name, rx, allowed in PATTERNS:
            if mod in allowed:
                continue
            if name == "import_generation_engine" and mod not in SERVICES_NO_ENGINE:
                continue
            n = len(re.findall(rx, src, flags=re.M))
            if n:
                counts.setdefault(name, {})[p.relative_to(ROOT).as_posix()] = n
    return counts


def test_leaves_import_only_stdlib_pip_or_leaves():
    project = _project_modules()
    bad = {}
    for leaf in sorted(LEAVES):
        p = ROOT / f"{leaf}.py"
        assert p.exists(), f"foglia dichiarata ma assente: {leaf}"
        offenders = sorted(m for m in _imports(p) if m in project and m not in LEAVES and m != leaf)
        if offenders:
            bad[leaf] = offenders
    assert not bad, f"foglie che importano moduli non-foglia: {bad}"


def test_nobody_imports_the_entry_point():
    bad = [p.name for p in _scan_files()
           if p.stem != "audiobook_app" and "audiobook_app" in _imports(p)]
    assert not bad, f"moduli che importano audiobook_app: {bad}"


def test_forbidden_patterns_do_not_grow():
    assert BASELINE.exists(), "manca test/boundaries_baseline.json: python test/test_module_boundaries.py"
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    now = compute_counts()
    grown, shrunk = [], []
    for name, _rx, _allowed in PATTERNS:
        for f in set(base.get(name, {})) | set(now.get(name, {})):
            b = base.get(name, {}).get(f, 0)
            n = now.get(name, {}).get(f, 0)
            if n > b:
                grown.append(f"{name}: {f} {b} -> {n}")
            elif n < b:
                shrunk.append(f"{name}: {f} {b} -> {n}")
    assert not grown, ("pattern vietati in aumento (REGOLE_CODICE.md §11.4):\n  "
                       + "\n  ".join(grown))
    if shrunk:
        # Non e' un errore: e' il momento di abbassare la baseline.
        print("baseline da aggiornare (in diminuzione):\n  " + "\n  ".join(shrunk))


if __name__ == "__main__":
    counts = compute_counts()
    if BASELINE.exists():
        old = json.loads(BASELINE.read_text(encoding="utf-8"))
        for name in counts:
            for f, n in counts[name].items():
                if n > old.get(name, {}).get(f, 0):
                    sys.exit(f"RIFIUTATO: {name} in {f} salirebbe da "
                             f"{old.get(name, {}).get(f, 0)} a {n}")
    BASELINE.write_text(json.dumps(counts, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(sum(v.values()) for v in counts.values())
    print(f"baseline scritta: {total} occorrenze in {len(counts)} pattern")
