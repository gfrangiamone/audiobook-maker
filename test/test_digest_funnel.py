"""Tests for Task A8: funnel block in admin digest + privacy policy update."""


def test_funnel_block_html_with_provider(monkeypatch):
    import email_service as es
    es.set_funnel_provider(lambda: {
        "app_open": {"total": 12}, "web_visit_from_app": {"total": 6},
        "payment_from_app": {"total": 2}, "conversion_rate": 0.3333})
    html = es._funnel_block_html()
    assert "12" in html and "6" in html and "2" in html and "33.3%" in html
    es.set_funnel_provider(None)


def test_funnel_block_html_no_provider():
    import email_service as es
    es.set_funnel_provider(None)
    assert es._funnel_block_html() == ""


def test_privacy_text_updated():
    """La privacy riflette la raccolta di metriche: traffico web misurato in
    forma aggregata via Google Analytics solo previo consenso, e un segnale di
    avvio dell'app a fini statistici (funnel, Task A8)."""
    import privacy_content as pc
    it = pc.render_privacy_page("it")
    en = pc.render_privacy_page("en")
    # Metriche web in forma aggregata, previo consenso esplicito.
    assert "in forma aggregata" in it
    assert "previo tuo consenso" in it
    assert "aggregate traffic" in en
    assert "with your consent" in en
    # Segnale di avvio app a fini statistici (funnel Task A8).
    assert "segnale di avvio" in it
    assert "app-open signal" in en
