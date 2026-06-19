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
    import privacy_content as pc
    it = pc.render_privacy_page("it")
    en = pc.render_privacy_page("en")
    assert "anonime e aggregate" in it
    assert "anonymous, aggregate" in en
    assert "non</strong> utilizza strumenti di analisi" not in it
