"""Test della finestra di protezione del marker email (.email_sent).

Regressione: un marker timestamp legacy veniva protetto con la finestra MAX
(Gemini, ~96h) per OGNI job, perche' il file su disco non registrava il tipo
voce. Risultato: cartelle di job standard (retention reale 18h) rimaste su
disco fino a 96h dopo un restart del service. Il marker self-describing incide
la finestra corretta per tipo voce, mantenendo il fallback conservativo.
"""
import time
import audiobook_app as app


def _make_marker(tmp_path, content):
    (tmp_path / app.EMAIL_MARKER_FILENAME).write_text(content, encoding="utf-8")
    return tmp_path


def test_standard_marker_window_is_email_retention(tmp_path):
    """Voce standard: marker auto-descrittivo protetto solo per EMAIL_FILE_RETENTION_SEC."""
    now = time.time()
    app._write_email_marker(tmp_path, when=now, is_gemini=False)
    content = (tmp_path / app.EMAIL_MARKER_FILENAME).read_text(encoding="utf-8")
    assert content == f"{now:.3f}|{app.EMAIL_FILE_RETENTION_SEC}"
    # Protetto subito dopo l'invio.
    assert app._email_marker_protects(tmp_path, now + 60)
    # Oltre EMAIL_FILE_RETENTION_SEC + 300: NON piu' protetto (niente over-hold a 96h).
    assert not app._email_marker_protects(tmp_path, now + app.EMAIL_FILE_RETENTION_SEC + 301)


def test_gemini_marker_window_is_extended(tmp_path):
    """Voce PREMIUM: finestra estesa no-download (prudenza massima sui file)."""
    now = time.time()
    app._write_email_marker(tmp_path, when=now, is_gemini=True)
    win = app.GEMINI_FILE_RETENTION_SEC * app.GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER
    content = (tmp_path / app.EMAIL_MARKER_FILENAME).read_text(encoding="utf-8")
    assert content == f"{now:.3f}|{win}"
    # Ancora protetto entro la finestra Gemini estesa.
    assert app._email_marker_protects(tmp_path, now + win - 600)
    # Oltre la finestra estesa: non piu' protetto.
    assert not app._email_marker_protects(tmp_path, now + win + 301)


def test_legacy_marker_uses_conservative_window(tmp_path):
    """Marker legacy (solo timestamp): fallback conservativo al max() — file preservato."""
    now = time.time()
    _make_marker(tmp_path, f"{now:.3f}")
    conservative = max(
        app.EMAIL_FILE_RETENTION_SEC,
        app.GEMINI_FILE_RETENTION_SEC * app.GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER,
    )
    # Entro la finestra conservativa un marker legacy resta protetto (storico, prudente).
    assert app._email_marker_protects(tmp_path, now + conservative - 600)
    assert not app._email_marker_protects(tmp_path, now + conservative + 301)


def test_unknown_voice_writes_legacy_form(tmp_path):
    """is_gemini=None (tipo voce ignoto): si scrive la forma legacy conservativa."""
    now = time.time()
    app._write_email_marker(tmp_path, when=now, is_gemini=None)
    content = (tmp_path / app.EMAIL_MARKER_FILENAME).read_text(encoding="utf-8")
    assert content == f"{now:.3f}"


def test_corrupt_window_falls_back_conservative(tmp_path):
    """Suffisso finestra corrotto: fallback conservativo, non si cancella per errore."""
    now = time.time()
    _make_marker(tmp_path, f"{now:.3f}|notanumber")
    conservative = max(
        app.EMAIL_FILE_RETENTION_SEC,
        app.GEMINI_FILE_RETENTION_SEC * app.GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER,
    )
    assert app._email_marker_protects(tmp_path, now + conservative - 600)
    assert not app._email_marker_protects(tmp_path, now + conservative + 301)


def test_pending_does_not_degrade_self_describing_marker(tmp_path):
    """Un marker 'inviato' self-describing NON deve essere degradato a 'pending'
    da una successiva scrittura pending (preserva la finestra di protezione)."""
    now = time.time()
    app._write_email_marker(tmp_path, when=now, is_gemini=True)
    before = (tmp_path / app.EMAIL_MARKER_FILENAME).read_text(encoding="utf-8")
    app._write_email_pending_marker(tmp_path)
    after = (tmp_path / app.EMAIL_MARKER_FILENAME).read_text(encoding="utf-8")
    assert after == before
    assert "|" in after  # ancora self-describing, non "pending"


def test_pending_marker_unchanged(tmp_path):
    """Il marker 'pending' resta protetto entro EMAIL_PENDING_MAX_AGE_SEC."""
    now = time.time()
    app._write_email_pending_marker(tmp_path)
    assert app._email_marker_protects(tmp_path, now + 60)
