"""Registro delle voci dentro `user_voices/` e replica permanente su R2.

Il registro `_voice_clones.json` vive accanto ai campioni, e l'intera
cartella `user_voices/` ha su R2 uno specchio fedele: registro caricato a ogni
scrittura (piu' una copia datata al giorno), file dei campioni caricati se
mancano, prefissi delle voci finite cancellati. Un server nuovo senza registro
locale lo recupera da R2 prima di crearne uno vuoto.
"""
import json
import os

import pytest

import community_store
import storage_backend
import voice_clone as vc


class FakeR2:
    """Bucket in memoria con la stessa API di storage_backend usata qui."""

    def __init__(self):
        self.objs = {}
        self.fail = None

    def _check(self):
        if self.fail:
            raise self.fail

    def upload_file(self, path, key):
        self._check()
        with open(path, "rb") as f:
            self.objs[key] = f.read()

    def upload_bytes(self, data, key):
        self._check()
        self.objs[key] = bytes(data)

    def download_file(self, key, path):
        self._check()
        if key not in self.objs:
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(self.objs[key])
        return True

    def list_prefix(self, prefix):
        self._check()
        return sorted(k for k in self.objs if k.startswith(prefix))

    def delete_prefix(self, prefix):
        self._check()
        for k in [k for k in self.objs if k.startswith(prefix)]:
            del self.objs[k]

    def delete_object(self, key):
        self._check()
        self.objs.pop(key, None)


@pytest.fixture
def r2(monkeypatch):
    fake = FakeR2()
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    for nome in ("upload_file", "upload_bytes", "download_file", "list_prefix",
                 "delete_prefix", "delete_object"):
        monkeypatch.setattr(storage_backend, nome, getattr(fake, nome))
    return fake


@pytest.fixture(autouse=True)
def niente_thread(monkeypatch):
    # Nei test la replica del registro si scarica a mano con flush_replica():
    # nessun thread in background che corre fra un'asserzione e l'altra.
    monkeypatch.setattr(vc, "_start_replica_thread", lambda: None)
    yield
    vc._replica_reset()


def _init(tmp_path, monkeypatch, r2_attivo=False):
    if not r2_attivo:
        monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    community_store.init(tmp_path)
    vc.init(tmp_path)


def _file(tmp_path, name, content=b"RIFF-finto"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def bozza(tmp_path, cid="cid-uno"):
    return vc.create_draft(cid, lang="it", locale="it-IT", gender="f", prompt_text="Frase.",
                           sample_wav=_file(tmp_path, f"{cid}-s.wav"),
                           original_path=_file(tmp_path, f"{cid}-o.webm", b"webm"),
                           original_ext="webm", metrics={}, ui_lang="it")


def _chiave_registro():
    return vc.R2_PREFIX + vc.STORE_FILENAME


# --- posizione del registro -------------------------------------------------

def test_il_registro_sta_dentro_user_voices(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    rec = bozza(tmp_path)
    assert vc.store_path() == os.path.join(str(tmp_path), "user_voices", "_voice_clones.json")
    assert not (tmp_path / "_voice_clones.json").exists()
    dati = json.loads((tmp_path / "user_voices" / "_voice_clones.json").read_text("utf-8"))
    assert [it["id"] for it in dati["items"]] == [rec["id"]]


def test_il_registro_nella_radice_viene_spostato(tmp_path, monkeypatch):
    vecchio = {"items": [{"id": "vc_vecchia", "state": "ready", "token": "a" * 32}]}
    (tmp_path / "_voice_clones.json").write_text(json.dumps(vecchio), "utf-8")
    (tmp_path / "_voice_clones.json.bak").write_text(json.dumps({"items": []}), "utf-8")
    _init(tmp_path, monkeypatch)
    assert vc.get("vc_vecchia") is not None
    assert not (tmp_path / "_voice_clones.json").exists()
    assert not (tmp_path / "_voice_clones.json.bak").exists()
    assert (tmp_path / "user_voices" / "_voice_clones.json.bak").exists()


def test_se_esistono_entrambi_vince_quello_in_user_voices(tmp_path, monkeypatch, capsys):
    (tmp_path / "user_voices").mkdir()
    (tmp_path / "user_voices" / "_voice_clones.json").write_text(
        json.dumps({"items": [{"id": "vc_nuova"}]}), "utf-8")
    (tmp_path / "_voice_clones.json").write_text(json.dumps({"items": [{"id": "vc_vecchia"}]}), "utf-8")
    _init(tmp_path, monkeypatch)
    assert vc.get("vc_nuova") is not None and vc.get("vc_vecchia") is None
    assert (tmp_path / "_voice_clones.json").exists()      # non si cancella nulla alla cieca
    assert "_voice_clones.json" in capsys.readouterr().out


# --- recupero da R2 all'avvio -----------------------------------------------

def test_server_nuovo_recupera_il_registro_da_r2(tmp_path, monkeypatch, r2):
    r2.objs[_chiave_registro()] = json.dumps({"items": [{"id": "vc_da_r2"}]}).encode()
    _init(tmp_path, monkeypatch, r2_attivo=True)
    assert vc.get("vc_da_r2") is not None


def test_registro_assente_anche_su_r2_parte_vuoto_e_si_replica(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    rec = bozza(tmp_path)
    assert vc.flush_replica() is True
    su_r2 = json.loads(r2.objs[_chiave_registro()])
    assert [it["id"] for it in su_r2["items"]] == [rec["id"]]


def test_r2_irraggiungibile_all_avvio_blocca_la_replica(tmp_path, monkeypatch, r2):
    """Senza registro locale e con R2 in errore non si sa se su R2 c'e' un
    registro buono: caricarne uno vuoto lo cancellerebbe. La replica resta
    sospesa finche' il processo non riparte."""
    buono = json.dumps({"items": [{"id": "vc_buona"}]}).encode()
    r2.objs[_chiave_registro()] = buono
    r2.fail = ConnectionError("rete giu'")
    monkeypatch.setattr(vc, "_RESTORE_PAUSE_SEC", 0)
    _init(tmp_path, monkeypatch, r2_attivo=True)
    r2.fail = None
    bozza(tmp_path)
    assert vc.flush_replica() is False
    assert r2.objs[_chiave_registro()] == buono


def test_registro_locale_presente_non_si_scarica(tmp_path, monkeypatch, r2):
    (tmp_path / "user_voices").mkdir()
    (tmp_path / "user_voices" / "_voice_clones.json").write_text(
        json.dumps({"items": [{"id": "vc_locale"}]}), "utf-8")
    r2.objs[_chiave_registro()] = json.dumps({"items": [{"id": "vc_da_r2"}]}).encode()
    _init(tmp_path, monkeypatch, r2_attivo=True)
    assert vc.get("vc_locale") is not None and vc.get("vc_da_r2") is None


# --- replica del registro -----------------------------------------------------

def test_ogni_scrittura_chiede_una_replica(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    assert vc.flush_replica() is False              # niente da caricare
    rec = bozza(tmp_path)
    assert vc.flush_replica() is True
    vc.rename(rec["id"], "cid-uno", "Nonna")
    assert vc.flush_replica() is True
    assert json.loads(r2.objs[_chiave_registro()])["items"][0]["name"] == "Nonna"
    assert vc.flush_replica() is False              # gia' allineato


def test_copia_datata_una_al_giorno_e_ne_restano_trenta(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    for giorno in range(1, 36):
        r2.objs[f"{vc.BACKUP_PREFIX}_voice_clones-2026-08-{giorno:02d}.json"
                if giorno <= 31 else
                f"{vc.BACKUP_PREFIX}_voice_clones-2026-09-{giorno - 31:02d}.json"] = b"{}"
    monkeypatch.setattr(vc, "_today", lambda: "2026-09-17")
    bozza(tmp_path)
    assert vc.flush_replica() is True
    copie = [k for k in r2.objs if k.startswith(vc.BACKUP_PREFIX)]
    assert len(copie) == vc.BACKUP_KEEP
    assert f"{vc.BACKUP_PREFIX}_voice_clones-2026-09-17.json" in copie
    assert f"{vc.BACKUP_PREFIX}_voice_clones-2026-08-01.json" not in copie
    # seconda scrittura nello stesso giorno: nessuna copia in piu'
    r2.objs.pop(f"{vc.BACKUP_PREFIX}_voice_clones-2026-09-17.json")
    vc.rename(vc._all()[0]["id"], "cid-uno", "Altro")
    assert vc.flush_replica() is True
    assert f"{vc.BACKUP_PREFIX}_voice_clones-2026-09-17.json" not in r2.objs


def test_un_registro_illeggibile_non_si_carica(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    bozza(tmp_path)
    assert vc.flush_replica() is True
    buono = r2.objs[_chiave_registro()]
    with open(vc.store_path(), "w", encoding="utf-8") as f:
        f.write("{tronc")
    vc._replica_mark_dirty()
    assert vc.flush_replica() is False
    assert r2.objs[_chiave_registro()] == buono


def test_errore_di_caricamento_lascia_la_replica_da_rifare(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    bozza(tmp_path)
    r2.fail = ConnectionError("rete giu'")
    assert vc.flush_replica() is False
    r2.fail = None
    assert vc.flush_replica() is True
    assert _chiave_registro() in r2.objs


def test_senza_r2_nessuna_replica(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    bozza(tmp_path)
    assert vc.flush_replica() is False


# --- allineamento dei file ------------------------------------------------------

def test_sync_carica_i_file_mancanti_su_r2(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    rec = bozza(tmp_path)                           # upload saltato: R2 "spento"
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    out = vc.sync_r2()
    pre = vc.R2_PREFIX + rec["token"] + "/"
    assert set(r2.objs) >= {pre + "sample.wav", pre + "original.webm"}
    assert out["uploaded"] == 2
    assert vc.sync_r2()["uploaded"] == 0             # gia' allineato


def test_sync_le_demo_solo_quando_la_voce_e_pronta(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    rec = bozza(tmp_path)
    d = vc.voice_dir(rec["token"])
    for nome in vc.DEMO_NAMES + ("demo_try_1_common.wav", "demo_common.pcm"):
        with open(os.path.join(d, nome), "wb") as f:
            f.write(b"x")
    vc.sync_r2()
    pre = vc.R2_PREFIX + rec["token"] + "/"
    assert not any(k.startswith(pre + "demo") for k in r2.objs)
    for s in ("paid", "demos_generating", "demos_ready", "ready"):
        vc.transition(rec["id"], s)
    vc.sync_r2()
    demo = sorted(k[len(pre):] for k in r2.objs if k.startswith(pre + "demo"))
    assert demo == sorted(vc.DEMO_NAMES)


def test_sync_cancella_su_r2_le_voci_finite(tmp_path, monkeypatch, r2):
    _init(tmp_path, monkeypatch, r2_attivo=True)
    rec = bozza(tmp_path)
    vc.transition(rec["id"], "paid")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    vc.transition(rec["id"], "refunded")
    vc.remove_files(rec)                            # R2 "spento": resta la copia remota
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    pre = vc.R2_PREFIX + rec["token"] + "/"
    assert any(k.startswith(pre) for k in r2.objs)
    out = vc.sync_r2()
    assert out["removed"] == 1
    assert not any(k.startswith(pre) for k in r2.objs)


def test_sync_non_tocca_prefissi_senza_record(tmp_path, monkeypatch, r2, capsys):
    """Un token su R2 senza record puo' voler dire registro perso o rovinato:
    cancellare sarebbe irreversibile (incidente voices/ del 12/09/2026)."""
    _init(tmp_path, monkeypatch, r2_attivo=True)
    ignoto = vc.R2_PREFIX + "f" * 32 + "/sample.wav"
    r2.objs[ignoto] = b"RIFF"
    r2.objs[_chiave_registro()] = b"{}"
    r2.objs[vc.BACKUP_PREFIX + "_voice_clones-2026-09-17.json"] = b"{}"
    out = vc.sync_r2()
    assert ignoto in r2.objs and out["unknown"] == 1
    assert "f" * 32 not in capsys.readouterr().out   # mai il token nei log


def test_sync_senza_r2_non_fa_nulla(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    bozza(tmp_path)
    assert vc.sync_r2() == {"uploaded": 0, "removed": 0, "unknown": 0}



def test_il_supervisore_allinea_r2_all_avvio_e_dopo_ogni_sweep():
    src = open(os.path.join(os.path.dirname(__file__), "..", "audiobook_app.py"), encoding="utf-8").read()
    inizio = src.index("def _voice_clone_sweep_supervisor():")
    corpo = src[inizio:src.index("\ndef ", inizio + 10)]
    assert corpo.count("voice_clone.sync_r2()") == 1
    # la sync precede lo sleep del ciclo (gira anche all'avvio) e non dipende
    # dal flag della feature: i dati esistenti vanno replicati comunque
    assert corpo.index("voice_clone.sync_r2()") < corpo.index("time.sleep(voice_clone.SWEEP_INTERVAL_SEC)")
    assert corpo.index("voice_clone.sync_r2()") < corpo.index("voice_clone.enabled()")
