"""Regressione: nomi file troncati a byte UTF-8, non a caratteri.

Incidente 23/08/2026: due job con titolo cinese sono morti con
`OSError: [Errno 36] File name too long` scrivendo `output_1/<titolo>.mp3`.
`_safe_filename` troncava a 100 *caratteri*; in UTF-8 un ideogramma CJK occupa
3 byte (un'emoji 4), quindi il nome superava i 255 byte per componente
ammessi da ext4. Il thread moriva in silenzio lasciando il job in `running`.
"""
import pytest

from audio_utils import MAX_FILENAME_BYTES, _safe_filename, truncate_filename

# Limite reale del filesystem di produzione (ext4), per componente del path.
EXT4_NAME_MAX = 255

# Titoli dei due job uccisi in produzione (troncati qui a scopo di test).
CJK_TITLE = "枪炮、病菌与钢铁 人类社会的命运 精装典藏版 中信出版社 戴蒙德 著" * 4
CJK_TITLE_2 = "周浩晖推理悬疑经典集 共10册 死亡通知单 邪恶催眠师 摄魂谷 引家" * 4


@pytest.mark.parametrize("title", [CJK_TITLE, CJK_TITLE_2])
def test_cjk_title_fits_filesystem_limit(title):
    """Il nome sanitizzato + estensione sta nel limite di ext4."""
    name = _safe_filename(title)
    assert len(name.encode("utf-8")) <= MAX_FILENAME_BYTES
    # Come lo compone generation_engine nel ramo single-file / per capitolo.
    for candidate in (f"{name}.mp3", f"{name}_podcast.xml", f"001_{name}.mp3"):
        assert len(candidate.encode("utf-8")) < EXT4_NAME_MAX


def test_truncation_never_splits_a_multibyte_char():
    """Il taglio cade su un confine di carattere: nessun byte orfano."""
    for extra in range(0, 6):
        name = _safe_filename("漢" * 60 + "a" * extra)
        # Round-trip stretto: se avessimo tagliato a meta' di un ideogramma,
        # il decode con errors='strict' fallirebbe o resterebbe U+FFFD.
        assert name.encode("utf-8").decode("utf-8") == name
        assert "�" not in name


def test_emoji_title_fits():
    name = _safe_filename("📚" * 80)   # 4 byte per emoji
    assert len(name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert "�" not in name


def test_ascii_title_keeps_historical_100_char_limit():
    """Nessuna regressione sui titoli latini: restano 100 caratteri."""
    assert _safe_filename("a" * 200) == "a" * 100


def test_short_names_unchanged():
    assert _safe_filename("Il nome della rosa") == "Il_nome_della_rosa"
    assert _safe_filename("三体") == "三体"


def test_truncate_filename_passthrough():
    assert truncate_filename("") == ""
    assert truncate_filename(None) is None
    assert truncate_filename("abc", 10) == "abc"
    assert truncate_filename("abcdef", 3) == "abc"
