# -*- coding: utf-8 -*-
"""
Cartella del job cancellata sotto il thread di generazione.

Il cleanup per heartbeat perso cancella la job dir mentre un chunk e' ancora
in volo: il controllo di annullamento a inizio giro e' gia' passato, e i
ritentativi del motore durano piu' della finestra. Il thread se ne accorge
solo scrivendo, e finora ci moriva con un traceback incatenato — il fallback
al silenzio riprovava sullo stesso path mancante — che nel log risultava
indistinguibile da un guasto vero (106 rimozioni per heartbeat, 108 morti
silenziose in sette giorni).

Qui si prova il discriminante, non l'intera `run_generation`: quando i due
indizi valgono «cancellazione voluta» e quando no.
"""

import os

import generation_engine as ge


def job(**kw):
    d = {"cancelled": True}
    d.update(kw)
    return d


def test_la_cartella_sparita_su_un_job_annullato_e_il_cleanup(tmp_path):
    assert ge._job_dir_gone(job(), tmp_path / "non-esiste") is True


def test_la_cartella_al_suo_posto_non_e_sparita(tmp_path):
    """L'annullamento chiesto dall'utente lascia la cartella dov'era: il solo
    flag non deve bastare, o ogni guasto durante un annullamento verrebbe
    archiviato come cancellazione."""
    assert ge._job_dir_gone(job(), tmp_path) is False


def test_senza_annullamento_una_cartella_mancante_resta_un_guasto(tmp_path):
    """Un path di consegna andato a buon fine puo' aver ripulito la work dir:
    li' un errore successivo va ancora registrato come guasto, con marker
    forense e traceback."""
    assert ge._job_dir_gone({"cancelled": False}, tmp_path / "via") is False
    assert ge._job_dir_gone({}, tmp_path / "via") is False


def test_un_job_assente_non_fa_esplodere_il_gestore(tmp_path):
    """Si chiama da dentro un `except`: qualunque inciampo qui trasformerebbe
    una diagnosi in una seconda eccezione."""
    assert ge._job_dir_gone(None, tmp_path / "via") is False


def test_un_percorso_illeggibile_vale_non_e_sparita(tmp_path, monkeypatch):
    def _boom(_p):
        raise OSError("filesystem non disponibile")
    monkeypatch.setattr(os.path, "isdir", _boom)
    assert ge._job_dir_gone(job(), tmp_path) is False


def test_l_errore_dedicato_non_e_un_annullamento():
    """`_CancelledError` porta al path di annullamento (stato `analyzed`, quota
    gratuita NON stornata). Questo caso non e' quello: niente e' stato
    consegnato, l'esito resta `error` e la quota torna indietro."""
    assert not issubclass(ge._JobDirGoneError, ge._CancelledError)
    assert issubclass(ge._JobDirGoneError, Exception)
