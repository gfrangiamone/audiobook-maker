"""
HTML template for the Audiobook Maker landing page.

The template is assembled from modular fragments at startup:
  - _fragments/html_head.html         : HTML structure, CSS, early JS
  - _fragments/i18n_data.js           : UI translations (6 languages)
  - _fragments/free_books_data.js     : Free book sites data + functions
  - _fragments/podcast_guide_data.js  : Podcast guide (base64 images + per-language sections + About)
  - _fragments/seo_data.js            : SEO metadata per language + applySEO()
  - _fragments/html_tail.html         : Active jobs monitor, applyI18n, main app logic, closing tags
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent / "_fragments"

_FRAGMENT_ORDER = [
    "html_head.html",
    "i18n_data.js",
    "free_books_data.js",
    "podcast_guide_data.js",
    "seo_data.js",
    "html_tail.html",
]


def build_html_template(version: str = "") -> str:
    """Assemble the full HTML template from fragments.

    Args:
        version: Version string to display in the page (e.g., "2.0").
                 If provided, a discrete badge is added at bottom-left.

    Returns:
        Complete HTML string ready for render_template_string().
    """
    parts = []
    for fname in _FRAGMENT_ORDER:
        fpath = _FRAGMENTS_DIR / fname
        parts.append(fpath.read_text(encoding="utf-8"))

    html = "".join(parts)

    # Inject version badge before </body>
    if version:
        badge = (
            '<div id="appVersion" style="position:fixed;bottom:8px;left:12px;'
            'font-size:11px;color:var(--txm,#9e9890);opacity:0.6;'
            'font-family:monospace;z-index:1;pointer-events:none;'
            'user-select:none">v' + version + '</div>'
        )
        html = html.replace("</body>", badge + "\n</body>")

    return html
