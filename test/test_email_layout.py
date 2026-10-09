"""C4a: frammenti email in email_layout, un solo _i18n_send, ricevute e voucher da i18n/*.json."""
import ast
import os
import pathlib

os.environ.setdefault("ABM_BASE_URL", "http://localhost:5601")

import email_layout as L
import email_service as es
import i18n


def test_layout_and_footer():
    html = L.layout("<p>B</p>", "https://x")
    assert html.startswith('<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px;')
    assert "<p>B</p>" in html and "Audiobook Maker — https://x</p>" in html
    assert html.count("<hr") == 1 and html.rstrip().endswith("</div>")
    assert "Audiobook Maker — </p>" in L.layout("x", "")
    assert ";color:#333" in L.layout("x", "", extra_style=";color:#333")


def test_voucher_box_and_refund_blocks():
    box = L.voucher_box("AB-12", "7.50", "01/01/2027", code_label="Codice:", value_label="Valore", expiry_label="Scade")
    assert "dashed #8b5cf6" in box and ">AB-12<" in box and "Valore: <strong>7.50 EUR</strong>" in box
    assert "Codice:" in box and "Scade: 01/01/2027" in box
    plain = L.voucher_box("AB-12", "7.50")
    assert "margin-bottom:8px" not in plain and "Scadenza" not in plain
    t = i18n.load("premium_emails")["it"]
    blk = L.voucher_refund_block("AB-12", "7.50", "01/01/2027", "USA <strong>u@x.it</strong>", t)
    assert "Codice buono di rimborso:" in blk and "<p>USA <strong>u@x.it</strong></p>" in blk
    green = L.refund_credited("<strong>X</strong> 3.00 EUR")
    assert "#f0fff4" in green and "<strong>X</strong> 3.00 EUR" in green
    assert "#fff7ed" in L.notice("x")


def test_admin_alert_and_panel():
    rows = L.row("A", "1", width="40%") + L.row("B", "2", last=True, mono=True)
    html = L.admin_alert("T", "#c0392b", subtitle_html="S", lead_html="LEAD", rows_html=rows,
                         after_html="<p>after</p>", note_html="note")
    assert "max-width:680px" in html and "background:#c0392b" in html and ">T</h2>" in html
    assert "width:40%" in html and "font-family:monospace" in html and "border-bottom" in rows
    assert html.index("LEAD") < html.index("<table") < html.index("<p>after</p>") < html.index("note")
    assert "<table" not in L.admin_alert("T", "#000")
    panel = L.admin_panel("P", "#1e8449", "<p>body</p>" + L.panel_table(L.kv("K", "V")))
    assert "max-width:640px" in panel and 'cellpadding="6"' in panel
    assert "<tr><td><strong>K</strong></td><td>V</td></tr>" in panel
    assert "border-left:4px solid #d97706" in L.callout("c")


def test_digest_page():
    page = L.digest_page("Title", "Sub", "<p>body</p>", ["n1", "n2"])
    assert page.startswith("<!DOCTYPE html>") and "linear-gradient" in page
    assert ">Title</h2>" in page and ">Sub</p>" in page and "<p>body</p>" in page
    assert page.count('color:#999;font-size:12px') == 2 and page.count("margin-top:16px") == 1
    assert page.rstrip().endswith("</body></html>")


def test_email_layout_is_a_leaf():
    src = pathlib.Path(L.__file__).read_text(encoding="utf-8")
    assert not [n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))]


def test_receipt_and_voucher_texts_from_json():
    rec, vou = i18n.load("receipt_emails"), i18n.load("voucher_emails")
    assert tuple(rec) == i18n.LANGS and tuple(vou) == i18n.LANGS
    for lg in i18n.LANGS:
        assert set(rec[lg]["service_names"]) >= {"optimization", "translation", "premium", "voice_clone"}
        assert "subject" in rec[lg] and rec[lg]["service"]        # etichetta "Servizio", non la mappa
        assert set(vou[lg]["what_names"]) >= {"optimization", "translation"} and vou[lg]["heading"]
    assert es._RECEIPT_SERVICE["en"] == rec["en"]["service_names"]
    assert es._VOUCHER_WHAT["it"] == vou["it"]["what_names"]


def test_user_emails_share_wrapper_and_footer(monkeypatch):
    sent = []
    monkeypatch.setattr(es, "_send_email", lambda to, subj, html, **k: sent.append(html) or True)
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "BASE_URL", "https://x")
    es._send_payment_receipt_email("ORD", "u@x.it", 9.5, kind="translation", lang="en")
    es._send_voucher_email("V-1", "u@x.it", 7.52, "Libro", kind="optimization", lang="fr")
    es._send_voucher_notification_email("V-2", "u@x.it", 5.0, 30, 0)
    es._send_gemini_overload_email("u@x.it", 4.0, "Libro", voucher_code="V-3", retry_after_sec=7200)
    es._send_gemini_failed_refund_email("u@x.it", 4.0, "Libro", "quota", voucher_code=None)
    es._send_gemini_cancelled_partial_email("u@x.it", 10.0, 6.0, 4.0, None, "Libro", "https://x/dl")
    assert len(sent) == 6
    for html in sent:
        assert html.count("Audiobook Maker — https://x</p>") == 1, html[-200:]
        assert html.startswith('<div style="font-family:system-ui,-apple-system,sans-serif;max-width:600px')
    assert "Service: <strong>Book translation</strong>" in sent[0]
    assert ">V-1<" in sent[1] and "dashed" in sent[1]
    assert "Value: <strong>5.00 EUR</strong>" in sent[2] and ";color:#333" in sent[2]
    assert "Codice buono di rimborso:" in sent[3] and ">V-3<" in sent[3]
    assert "Rimborso accreditato:" in sent[4]
    assert "Rimborso accreditato:" in sent[5] and "4.00 EUR" in sent[5]


def test_admin_alerts_use_layout(monkeypatch):
    sent = []
    monkeypatch.setattr(es, "_send_email", lambda to, subj, html, **k: sent.append((subj, html)) or True)
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "ADMIN_EMAIL", "admin@x.it")
    monkeypatch.setattr(es, "_admin_failure_last", {})
    es._admin_notify_gemini_failure("job-1234", "quota", 3.0, "u@x.it", "Libro", "failed_quota_refunded",
                                    reason_detail="d", voucher_code="V", chunks_total=10, chunks_failed=2,
                                    chars_total=1234)
    es.admin_notify_margin_anomaly("job-5678", "below_expected", "gemini", book_title="Libro",
                                   revenue_eur=10, cost_est_eur=1, cost_actual_eur=5, list_actual_eur=20,
                                   threshold_eur=2, margin_expected_eur=9, margin_actual_eur=5, chars_total=10)
    es.admin_notify_tts_backend_switch("gemini-x", "cf_backend_down", "boom", "job-1", credit_left_usd=1.5)
    es.admin_notify_gemini_model_unavailable("gemini-x", "err", "job-2", 600)
    assert len(sent) == 4
    fail, margin, switch, unavail = (h for _s, h in sent)
    assert "Gemini TTS — QUOTA esaurita" in fail and "<strong>Chunk</strong>" in fail and "2/10 falliti" in fail
    assert "voucher PayPal <code>V</code>" in fail and "1,234" in fail and "tab-gemini" in fail
    assert fail.count("padding:8px 12px") >= 12 and "font-family:monospace" in fail
    assert "Margine" in margin and "<strong>Libro</strong>" in margin and "width:46%" in margin
    assert "Costo provider reale" in margin and "audit-premium" in margin
    assert "passaggio automatico a Vertex" in switch and "Credito residuo (stima)</strong></td><td>1.50 USD" in switch
    assert "Modello TTS non disponibile" in unavail and "<code>gemini-x</code>" in unavail
    assert switch.count("border-radius:8px 8px 0 0") == 1 and unavail.count("border-radius:8px 8px 0 0") == 1


def test_vc_and_acct_senders_share_i18n_send(monkeypatch):
    sent = []
    monkeypatch.setattr(es, "_send_email", lambda to, subj, html, **k: sent.append((to, subj, html)) or True)
    assert es.send_account_deleted("u@x.it", "it") is True
    assert es.send_voice_clone_expiring("u@x.it", "en", days=3, manage_url="https://x/m") is True
    assert len(sent) == 2 and "https://x/m" in sent[1][2]
    assert es.send_account_deleted("", "it") is False
    src = pathlib.Path(es.__file__).read_text(encoding="utf-8")
    assert src.count("def _i18n_send(") == 1 and "safe = {k:" in src and src.count("safe = {k:") == 1
    assert "dashed #8b5cf6" not in src and "linear-gradient" not in src and "<!DOCTYPE" not in src


# ---- C4b: email PREMIUM localizzate --------------------------------------------------

def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(es, "_send_email", lambda to, subj, html, **k: sent.append((subj, html)) or True)
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "BASE_URL", "https://x")
    return sent


def test_premium_emails_italian_texts_unchanged(monkeypatch):
    sent = _capture(monkeypatch)
    es._send_gemini_overload_email("u@x.it", 4.0, "Libro", voucher_code="V-3", retry_after_sec=7200)
    es._send_gemini_failed_refund_email("u@x.it", 5.28, "Libro", "quota", voucher_code=None)
    es._send_gemini_cancelled_partial_email("u@x.it", 2.0, 0.71, 1.29, "REF-ABC", "Libro",
                                            "https://x/dl/TOK", lang="it")
    es._send_gemini_cancelled_partial_email("u@x.it", 2.0, 2.0, 0.0, None, "Libro",
                                            "https://x/dl/TOK", lang="it", auto_cancel=True)
    (s1, h1), (s2, h2), (s3, h3), (s4, h4) = sent
    assert s1 == "Audiobook Maker — Generazione non avviata, rimborso emesso (4.00 EUR)"
    assert "Generazione audio non avviata" in h1 and "<strong>Libro</strong> non &egrave; stata avviata" in h1
    assert "entro <strong>2 ore</strong>" in h1 and "Codice buono di rimborso:" in h1 and ">V-3<" in h1
    assert "Ti chiediamo scusa per il disagio.</p>" in h1
    assert s2 == "Audiobook Maker — Generazione interrotta, rimborso emesso (5.28 EUR)"
    assert "<strong>Motivo:</strong> il provider del servizio voci ha esaurito la quota giornaliera" in h2
    assert "<strong>Rimborso accreditato:</strong> 5.28 EUR sono stati ri-accreditati" in h2
    assert s3.startswith("Audiobook Maker — Generazione annullata") and "(1.29 EUR rimborsati)" in s3
    assert "hai annullato la generazione" in h3 and ">REF-ABC<" in h3 and "https://x/dl/TOK" in h3
    assert "Scarica l'audio parziale (MP3)" in h3 and "Quota trattenuta" in h3 and "0.71 EUR" in h3
    assert s4.startswith("Audiobook Maker — Generazione interrotta") and "Generazione interrotta</h2>" in h4
    assert "consegna via email" in h4 and "Nessun rimborso residuo" in h4 and "(2.00 EUR)" in h4


def test_premium_emails_english_and_fallback(monkeypatch):
    sent = _capture(monkeypatch)
    es._send_gemini_overload_email("u@x.it", 4.0, "", voucher_code=None, retry_after_sec=3600, lang="en")
    es._send_gemini_failed_refund_email("u@x.it", 5.0, "Book", "budget", voucher_code="V", lang="pt")
    es._send_gemini_failed_refund_email("u@x.it", 5.0, "Book", "testo <b>libero</b>", lang="ja-JP")
    es._send_gemini_cancelled_partial_email("u@x.it", 2.0, 0.5, 1.5, None, "Book", "https://x/d", lang="ru")
    (s1, h1), (s2, h2), (s3, h3), (s4, h4) = sent
    assert s1 == "Audiobook Maker — Generation not started, refund issued (4.00 EUR)"
    assert "<strong>your book</strong>" in h1 and "within <strong>1 hour</strong>" in h1
    assert "<strong>Refund credited:</strong> 4.00 EUR" in h1 and "Ciao" not in h1
    assert "daily spending limit" in h2 and "Refund voucher code:" in h2 and ">V<" in h2   # pt -> en
    assert "<strong>Reason:</strong> testo &lt;b&gt;libero&lt;/b&gt;" in h3
    assert "Refund details" in h4 and "Download the partial audio (MP3)" in h4 and "1.50 EUR" in h4
    for h in (h1, h2, h3, h4):
        assert "Gemini" not in h and "__" not in h and "{" not in h


def test_premium_emails_translated_languages(monkeypatch):
    """C4b (2026-10-09): fr/es/de/zh/hi hanno i loro testi; nessun placeholder
    o nome di fornitore nel risultato."""
    sent = _capture(monkeypatch)
    expected = {"fr": "Génération", "es": "Generación", "de": "Generierung", "zh": "生成", "hi": "जनरेशन"}
    for lang in expected:
        es._send_gemini_overload_email("u@x.it", 4.0, "", voucher_code=None, retry_after_sec=7200, lang=lang)
        es._send_gemini_failed_refund_email("u@x.it", 5.0, "Book", "quota", voucher_code="V", lang=lang)
        es._send_gemini_cancelled_partial_email("u@x.it", 2.0, 0.5, 1.5, None, "Book", "https://x/d", lang=lang)
    assert len(sent) == 15
    for i, lang in enumerate(expected):
        for subj, html in sent[3 * i:3 * i + 3]:
            assert expected[lang] in subj and "Audiobook Maker" in subj
            assert "Gemini" not in html and "{" not in html and "__" not in html
            assert "Generation" not in subj                                   # non e' il fallback inglese
        assert ">V<" in sent[3 * i + 1][1] and "https://x/d" in sent[3 * i + 2][1]


def test_premium_json_complete_and_placeholders():
    data = i18n.load("premium_emails")
    assert set(data) == {"it", "en", "fr", "es", "de", "zh", "hi"}
    import re
    for lang in data:
        assert set(data[lang]) == set(data["it"]), lang
        for key, it_text in data["it"].items():
            other = data[lang][key]
            if isinstance(it_text, dict):
                assert set(it_text) == set(other) == {"quota", "budget", "quality", "interrupted_restart"}, lang
                continue
            assert set(re.findall(r"{(\w+)}", it_text)) == set(re.findall(r"{(\w+)}", other)), (lang, key)
            assert ("<strong>" in it_text) == ("<strong>" in other), (lang, key)
