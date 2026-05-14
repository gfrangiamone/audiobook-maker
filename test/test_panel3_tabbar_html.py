from pathlib import Path

HTML = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")

def test_panel3_has_tab_bar():
    assert 'id="panel3"' in HTML
    assert 'class="tab-bar"' in HTML
    assert 'data-tab="standard"' in HTML
    assert 'data-tab="premium"' in HTML

def test_panel3_has_two_tab_panels():
    assert 'id="tabStandard"' in HTML
    assert 'id="tabPremium"' in HTML
    assert 'role="tabpanel"' in HTML

def test_panel3_premium_tab_has_model_selector():
    assert 'id="vmPremium"' in HTML
    assert 'value="flash25"' in HTML
    assert 'value="flash31"' in HTML

def test_panel3_premium_tab_has_style_textarea():
    assert 'id="geminiStyle"' in HTML
    assert 'maxlength="300"' in HTML

def test_panel3_premium_tab_has_cost_preview_box():
    assert 'id="costPreviewBox"' in HTML
    assert 'id="costPreviewValue"' in HTML
