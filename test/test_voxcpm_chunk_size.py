"""Il chunking per voci VoxCPM deve usare il cap 300, non i 2000 di Edge.

VoxCPM2 e' autoregressivo e riancora il timbro al campione di riferimento
solo all'inizio di ogni chunk: dentro il chunk il conditioning si
auto-alimenta (`prefix_feat_cond = pred_feat`, issue OpenBMB/VoxCPM#302) e
su testi lunghi la voce deriva e il ritmo accelera. Il worker non rispezza i
`chunks` che riceve, quindi il tetto lo decide qui.

300 e' il valore con cui sono state prese tutte le misure del worker
(`abm-voxcpm-worker`, README): chunk mediano ~19 s a 13,8 car/s in italiano,
dell'ordine del campione di clone. Senza un ramo dedicato
`_pick_chunk_max_chars` cadeva su CHUNK_MAX_CHARS=2000: 132 chunk da ~142 s
sul libro del banco di prova.
"""
import tts_split
import voxcpm_tts

_VOCE = "voxcpm:v2:it-IT/Valentina"
_CLONE = "voxcpm:mine:abcdef0123456789"


def test_voxcpm_chunk_cap_is_300():
    got = tts_split._pick_chunk_max_chars(_VOCE, "it")
    assert got == voxcpm_tts.CHUNK_MAX_CHARS == 300


def test_cloned_voice_uses_the_same_cap():
    assert tts_split._pick_chunk_max_chars(_CLONE, "en") == 300


def test_voxcpm_has_no_byte_cap():
    # Il cap byte e' un vincolo dell'API Gemini; il worker non ne ha.
    assert tts_split._pick_chunk_max_bytes(_VOCE) is None


def test_other_engines_chunk_caps_unchanged():
    assert tts_split._pick_chunk_max_chars("en-US-AriaNeural", "en") == 2000
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "en") == 700
    assert tts_split._pick_chunk_max_chars("speechify:simba-3.2:hugh_32", "en") == 1800


def test_chunk_max_chars_default_matches_constant():
    assert voxcpm_tts.chunk_max_chars() == voxcpm_tts.CHUNK_MAX_CHARS == 300


def test_chunk_max_chars_env_override(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CHUNK_CHARS", "400")
    assert voxcpm_tts.chunk_max_chars() == 400
    # L'override si propaga al planner del chunking.
    assert tts_split._pick_chunk_max_chars(_VOCE, "it") == 400


def test_chunk_max_chars_env_clamped(monkeypatch):
    # Sotto il pavimento una frase non ci sta e lo splitter taglierebbe sulle
    # virgole; sopra i 2000 si supererebbe il cap degli altri motori.
    monkeypatch.setenv("ABM_VOXCPM_CHUNK_CHARS", "5")
    assert voxcpm_tts.chunk_max_chars() == voxcpm_tts.CHUNK_MIN_CHARS
    monkeypatch.setenv("ABM_VOXCPM_CHUNK_CHARS", "99999")
    assert voxcpm_tts.chunk_max_chars() == tts_split.CHUNK_MAX_CHARS


def test_chunk_max_chars_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CHUNK_CHARS", "abc")
    assert voxcpm_tts.chunk_max_chars() == voxcpm_tts.CHUNK_MAX_CHARS


def test_the_plan_for_a_voxcpm_voice_never_exceeds_the_cap():
    # Il tetto arriva fino ai chunk veri: nessuno supera 300 caratteri e le
    # frasi restano intere (ogni chunk finisce con un terminatore).
    frase = ("Il mattino dopo la nave lascio' il porto con il vento a favore "
             "e nessuno a bordo sapeva quanto sarebbe durata la traversata. ")
    testo = frase * 12
    cap = tts_split._pick_chunk_max_chars(_VOCE, "it")
    chunks = tts_split.split_text_into_chunks(testo, max_chars=cap)
    assert len(chunks) == 6
    assert all(len(c) <= 300 for c in chunks)
    assert all(c.endswith(".") for c in chunks)
