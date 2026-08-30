"""Qualita' delle traduzioni community: il modello a volte ricopia il testo
sorgente nello slot di un'altra lingua (incidente 30/08/2026: commento tedesco
servito verbatim come "traduzione" italiana). Questi test coprono il rilevamento
e lo scarto di quelle copie."""
import community_translator as ct


DE = ("Ich habe seit letzter Woche wann immer ich ein Hoerbuch erstellen lassen "
      "will mit Premium Sprache Deutsch eine Fehlermeldung erhalten")
IT = ("Da settimana scorsa ogni volta che provo a creare un audiolibro con voce "
      "premium tedesca ricevo un messaggio di errore")


def test_short_identical_text_is_not_flagged():
    # "nice", "goated", "Excellant" restano identici in ogni lingua: legittimo.
    assert ct._looks_untranslated("nice", "nice") is False
    assert ct._looks_untranslated("Great tool", "Great tool") is False


def test_long_identical_text_is_flagged():
    assert ct._looks_untranslated(DE, DE) is True
    # Il confronto ignora spaziatura e maiuscole.
    assert ct._looks_untranslated(DE, "  " + DE.upper() + " ") is True
    assert ct._looks_untranslated(DE, IT) is False


def test_needs_translation_detects_copied_slot():
    i18n = {lg: IT for lg in ct.LANGS}
    i18n["de"] = DE          # sorgente: copia lecita
    assert ct.needs_translation(DE, i18n, "de") is False
    i18n["it"] = DE          # copia in uno slot sbagliato
    assert ct.needs_translation(DE, i18n, "de") is True


def test_needs_translation_detects_missing_and_empty():
    assert ct.needs_translation(DE, {}, "de") is True
    partial = {lg: IT for lg in ct.LANGS}
    partial["de"] = DE
    partial["fr"] = ""
    assert ct.needs_translation(DE, partial, "de") is True
    assert ct.needs_translation("", {}, "de") is False


def test_drop_copied_slots_clears_only_wrong_languages():
    data = {lg: {"comment": IT} for lg in ct.LANGS}
    data["de"]["comment"] = DE
    data["it"]["comment"] = DE
    ct._drop_copied_slots(data, {"comment": DE}, "de")
    assert data["it"]["comment"] == ""      # copia scartata
    assert data["de"]["comment"] == DE      # sorgente intatta
    assert data["fr"]["comment"] == IT      # traduzione vera intatta


def test_drop_copied_slots_noop_without_source_lang():
    """Senza lingua sorgente attendibile non si distingue la copia lecita."""
    data = {lg: {"comment": DE} for lg in ct.LANGS}
    ct._drop_copied_slots(data, {"comment": DE}, "")
    assert all(data[lg]["comment"] == DE for lg in ct.LANGS)


def test_retry_fills_only_missing_slots(monkeypatch):
    data = {lg: {"comment": IT} for lg in ct.LANGS}
    data["de"]["comment"] = DE
    data["it"]["comment"] = ""              # buco lasciato dallo scarto
    calls = []

    def fake_call(payload, *, timeout, use_json_mode):
        calls.append(payload)
        import json
        out = {lg: {"comment": "RETRY-" + lg} for lg in ct.LANGS}
        return json.dumps(out)

    monkeypatch.setattr(ct, "_call_llm", fake_call)
    ct._retry_missing_slots(data, {"comment": DE}, "de", timeout=5)
    assert len(calls) == 1
    assert data["it"]["comment"] == "RETRY-it"
    assert data["fr"]["comment"] == IT       # non sovrascritto


def test_retry_rejects_copied_answer(monkeypatch):
    data = {lg: {"comment": IT} for lg in ct.LANGS}
    data["de"]["comment"] = DE
    data["it"]["comment"] = ""

    def fake_call(payload, *, timeout, use_json_mode):
        import json
        return json.dumps({lg: {"comment": DE} for lg in ct.LANGS})

    monkeypatch.setattr(ct, "_call_llm", fake_call)
    ct._retry_missing_slots(data, {"comment": DE}, "de", timeout=5)
    assert data["it"]["comment"] == ""       # la copia non viene accettata


def test_no_retry_when_complete(monkeypatch):
    data = {lg: {"comment": IT} for lg in ct.LANGS}
    data["de"]["comment"] = DE

    def boom(*a, **k):
        raise AssertionError("nessuna chiamata attesa")

    monkeypatch.setattr(ct, "_call_llm", boom)
    ct._retry_missing_slots(data, {"comment": DE}, "de", timeout=5)
