# 📚 Audiobook Maker

**Convert your EPUB, PDF and TXT ebooks into high-quality audiobooks using neural text-to-speech voices.**

Audiobook Maker (https://audiobook-maker.com) is a self-hosted web application that turns any EPUB, PDF or TXT file into a full audiobook in minutes. It leverages Microsoft Edge's neural TTS engine (via [edge-tts](https://github.com/rany2/edge-tts)) to produce natural-sounding audio in multiple languages, with no API keys, no subscriptions, and no data retention.

---

## ✨ Features

- **Neural TTS voices** — 300+ high-quality voices via edge-tts, covering Italian, English, French, Spanish, German, Chinese and more
- **EPUB, PDF & TXT support** — automatic chapter extraction, smart text cleaning (footnotes, captions, headers/footers removal for PDF), cover image display
- **Audio preview** — listen to a sample of your book with the selected voice and speed before generating the full audiobook
- **Flexible output** — single MP3 file or one file per chapter (ZIP archive)
- **Podcast mode** — generates an RSS 2.0 feed ready to publish as a private podcast
- **Chapter selection** — choose which chapters to include, reorder, select all / deselect all
- **Reading speed control** — from −30% to +30% in 7 steps
- **Email notification** — enter your email to receive a download link when a long generation completes, so you can close the browser
- **Dark / light theme**
- **Multilingual UI** — interface available in 🇮🇹 Italian, 🇬🇧 English, 🇫🇷 French, 🇪🇸 Spanish, 🇩🇪 German, 🇨🇳 Chinese
- **SEO-optimised** — server-side rendered meta tags, hreflang, canonical URLs and sitemap for all 6 languages
- **Privacy by design** — uploaded files and generated audio are automatically deleted after the session; nothing is stored permanently

---

## 🖥️ Requirements

- Python 3.10+
- [edge-tts](https://github.com/rany2/edge-tts) (`pip install edge-tts`)
- [Flask](https://flask.palletsprojects.com/) (`pip install flask`)
- Internet connection (edge-tts calls Microsoft's TTS service)

Optional:
- [PyMuPDF](https://pymupdf.readthedocs.io/) — for PDF support (`pip install pymupdf`)
- [Pillow](https://python-pillow.org/) — for cover image resizing (`pip install pillow`)
- SMTP server — for email notifications

---

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/gfrangiamone/audiobook-maker.git
cd audiobook-maker

# Install dependencies
pip install flask edge-tts

# Optional: PDF support and cover image resizing
pip install pymupdf pillow

# Run the app
python audiobook_app.py
```

Then open [http://localhost:5601](http://localhost:5601) in your browser.

---

## ⚙️ Configuration

All configuration is done via environment variables — no config files needed.

| Variable | Description | Default |
|---|---|---|
| `ABM_BASE_URL` | Public URL of your deployment (e.g. `https://audiobook-maker.com`) — required for hreflang, canonical and sitemap | *(empty)* |
| `ABM_DATA_DIR` | Directory for temporary job files | System temp dir |
| `ABM_SMTP_HOST` | SMTP host for email notifications | *(disabled)* |
| `ABM_SMTP_PORT` | SMTP port | `587` |
| `ABM_SMTP_USER` | SMTP username | *(empty)* |
| `ABM_SMTP_PASS` | SMTP password | *(empty)* |
| `ABM_SMTP_FROM` | Sender address | *(empty)* |
| `ABM_ADMIN_EMAIL` | Admin address for generation digest emails | *(disabled)* |

Example:
```bash
export ABM_BASE_URL=https://audiobook-maker.com
export ABM_SMTP_HOST=smtp.gmail.com
export ABM_SMTP_USER=you@gmail.com
export ABM_SMTP_PASS=your_app_password
python audiobook_app.py
```

---

## 🌐 Multilingual URL Structure

When `ABM_BASE_URL` is set, the app exposes dedicated URLs for each language, fully indexed by search engines:

| URL | Language |
|---|---|
| `/` | Auto-detected from `Accept-Language` |
| `/it/` | Italian |
| `/en/` | English |
| `/fr/` | French |
| `/es/` | Spanish |
| `/de/` | German |
| `/zh/` | Chinese |
| `/sitemap.xml` | Sitemap with hreflang for all 6 languages |
| `/robots.txt` | Robots file with sitemap reference |

---

## 🏗️ Project Structure

```
audiobook-maker/
├── audiobook_app.py          # Flask application, routes, job management
├── epub_to_tts.py            # EPUB parsing and chapter extraction
├── pdf_to_tts.py             # PDF parsing, text cleaning and chapter detection
├── version.py                # Version string
└── templates/
    ├── index_page.py         # Template assembly and SEO rendering
    └── _fragments/
        ├── html_head.html    # HTML structure, CSS, meta tags (SEO placeholders)
        ├── html_tail.html    # App logic, i18n, main JavaScript
        ├── i18n_data.js      # UI translations (6 languages)
        ├── seo_data.js       # SEO metadata per language
        ├── free_books_data.js
        └── podcast_guide_data.js
```

---

## 📄 License
This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-or-later).

Copyright (C) 2026
Giuseppe Frangiamone gfrangiamone@gmail.com

You are free to:

Use the software for any purpose, including commercial use

Study and modify the source code

Distribute copies of the original or modified software

Under the following conditions:

You must provide access to the full corresponding source code when distributing the software.

If you run a modified version of this application as a network service (e.g. a public or private web deployment), you must make the modified source code available to the users of that service.

You must retain copyright notices and license information.

This program is distributed without any warranty, without even the implied warranty of merchantability or fitness for a particular purpose. See the LICENSE.txt file for full details.

For the complete license text, see:
https://www.gnu.org/licenses/agpl-3.0.html


##⚖️ Legal Notice

Users are responsible for ensuring they have the legal right to convert and use the content they upload.
This software does not grant any rights over copyrighted materials.

The author assumes no liability for misuse of the software.

## 🙏 Acknowledgements

- [edge-tts](https://github.com/rany2/edge-tts) by rany2 — the TTS engine powering this project
- [EbookLib](https://github.com/aerkalov/ebooklib) — EPUB parsing
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF text extraction
- Microsoft Azure Cognitive Services — neural voice synthesis
