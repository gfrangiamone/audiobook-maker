"""_malloc_trim: restituisce l'heap glibc al SO senza mai poter rompere il loop.

Gira nel cleanup loop, che e' l'unico thread a fare hot-evict e retention: una
sua eccezione non gestita ha gia' riempito il disco al 100% in passato. Qui si
verifica che sia rate-limitato, no-op fuori da glibc e a prova di eccezione.
"""
import audiobook_app as app
import cleanup


def _reset():
    cleanup._last_malloc_trim[0] = 0.0
    del cleanup._libc_trim[:]


def test_trim_is_safe_and_resolves_once():
    _reset()
    cleanup._malloc_trim(1000.0, force=True)
    # Il simbolo viene risolto una sola volta e memorizzato (None se assente).
    assert len(cleanup._libc_trim) == 1
    resolved = cleanup._libc_trim[0]
    cleanup._malloc_trim(2000.0, force=True)
    assert len(cleanup._libc_trim) == 1 and cleanup._libc_trim[0] is resolved


def test_trim_is_rate_limited():
    _reset()
    cleanup._malloc_trim(1000.0, force=True)
    assert cleanup._last_malloc_trim[0] == 1000.0
    # Dentro la finestra: nessun lavoro, timestamp invariato.
    cleanup._malloc_trim(1000.0 + cleanup.MALLOC_TRIM_INTERVAL_SEC - 1)
    assert cleanup._last_malloc_trim[0] == 1000.0
    # Oltre la finestra: riparte.
    later = 1000.0 + cleanup.MALLOC_TRIM_INTERVAL_SEC + 1
    cleanup._malloc_trim(later)
    assert cleanup._last_malloc_trim[0] == later


def test_trim_swallows_libc_errors(capsys):
    _reset()

    def _boom(_):
        raise OSError("libc esplosa")

    cleanup._libc_trim.append(_boom)
    cleanup._malloc_trim(1000.0, force=True)   # non deve propagare
    assert "malloc_trim error" in capsys.readouterr().out
