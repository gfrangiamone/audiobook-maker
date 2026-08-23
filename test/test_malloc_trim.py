"""_malloc_trim: restituisce l'heap glibc al SO senza mai poter rompere il loop.

Gira nel cleanup loop, che e' l'unico thread a fare hot-evict e retention: una
sua eccezione non gestita ha gia' riempito il disco al 100% in passato. Qui si
verifica che sia rate-limitato, no-op fuori da glibc e a prova di eccezione.
"""
import audiobook_app as app


def _reset():
    app._last_malloc_trim[0] = 0.0
    del app._libc_trim[:]


def test_trim_is_safe_and_resolves_once():
    _reset()
    app._malloc_trim(1000.0, force=True)
    # Il simbolo viene risolto una sola volta e memorizzato (None se assente).
    assert len(app._libc_trim) == 1
    resolved = app._libc_trim[0]
    app._malloc_trim(2000.0, force=True)
    assert len(app._libc_trim) == 1 and app._libc_trim[0] is resolved


def test_trim_is_rate_limited():
    _reset()
    app._malloc_trim(1000.0, force=True)
    assert app._last_malloc_trim[0] == 1000.0
    # Dentro la finestra: nessun lavoro, timestamp invariato.
    app._malloc_trim(1000.0 + app.MALLOC_TRIM_INTERVAL_SEC - 1)
    assert app._last_malloc_trim[0] == 1000.0
    # Oltre la finestra: riparte.
    later = 1000.0 + app.MALLOC_TRIM_INTERVAL_SEC + 1
    app._malloc_trim(later)
    assert app._last_malloc_trim[0] == later


def test_trim_swallows_libc_errors(capsys):
    _reset()

    def _boom(_):
        raise OSError("libc esplosa")

    app._libc_trim.append(_boom)
    app._malloc_trim(1000.0, force=True)   # non deve propagare
    assert "malloc_trim error" in capsys.readouterr().out
