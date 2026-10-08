"""email_layout — frammenti HTML comuni alle email (utente e admin).

Modulo foglia (solo stdlib). Prima: wrapper e footer scritti a mano in sei
email, box voucher tratteggiato in cinque, blocco verde «rimborso
accreditato» in tre, alert admin con barra colorata + tabella in sei,
header a gradiente del digest in due moduli.

Tutti i valori ricevuti sono HTML gia' pronto (escapato dal chiamante);
le funzioni compongono soltanto.

- `layout(body, base_url)`: wrapper 600px + footer «Audiobook Maker — url».
- `voucher_box(code, amount, expiry)`: box tratteggiato viola del buono.
- `refund_credited(text)`, `voucher_refund_block(...)`: blocchi di rimborso
  delle email PREMIUM (testi dal chiamante, i18n/premium_emails.json).
- `admin_alert(title, color, rows=...)`: barra colorata + tabella a righe
  `row(label, value)`; `admin_panel(title, color, body)`: barra + riquadro
  libero con righe `kv(label, value)`.
- `digest_page(title, subtitle, body, notes)`: pagina dei digest admin.
"""

FONT = "font-family:system-ui,-apple-system,sans-serif"
_FOOTER_HR = '<hr style="border:none;border-top:1px solid #eee;margin:24px 0">'


def footer(base_url):
    """Riga di chiusura comune: separatore + «Audiobook Maker — <url>»."""
    return (f'{_FOOTER_HR}\n'
            f'  <p style="color:#999;font-size:12px">Audiobook Maker — {base_url or ""}</p>')


def layout(body, base_url, *, max_width=600, extra_style=""):
    """Email utente: wrapper centrato con font di sistema, corpo e footer."""
    return (f'<div style="{FONT};max-width:{max_width}px;margin:0 auto;padding:20px{extra_style}">\n'
            f'  {body}\n'
            f'  {footer(base_url)}\n'
            f'</div>')


def voucher_box(code, amount, expiry="", *, code_label="", value_label="Valore",
                expiry_label="Scadenza"):
    """Box tratteggiato del buono: codice in monospazio, valore, scadenza.
    `amount` e' gia' formattato ("12.50"); `code_label`/`expiry` opzionali."""
    label = (f'\n    <div style="font-size:.85em;color:#666;margin-bottom:8px">{code_label}</div>'
             if code_label else "")
    exp = (f'\n    <div style="margin-top:4px;font-size:.9em;color:#666">{expiry_label}: {expiry}</div>'
           if expiry else "")
    return (f'<div style="padding:20px;background:#f0f5ff;border:2px dashed #8b5cf6;border-radius:8px;'
            f'margin:20px 0;text-align:center">{label}\n'
            f'    <div style="font-family:monospace;font-size:1.6em;font-weight:700;letter-spacing:2px;'
            f'color:#8b5cf6">{code}</div>\n'
            f'    <div style="margin-top:12px">{value_label}: <strong>{amount} EUR</strong></div>{exp}\n'
            f'  </div>')


def refund_credited(text_html):
    """Blocco verde: importo ri-accreditato sul buono originale (il testo,
    gia' localizzato e con l'importo, lo passa il chiamante)."""
    return (f'<div style="padding:16px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;margin:20px 0">\n'
            f'    <p style="margin:0">{text_html}</p>\n  </div>')


def voucher_refund_block(code, amount, expiry, use_html, t):
    """Box del buono di rimborso + istruzioni d'uso. `t`: etichette
    localizzate (`voucher_code_label`, `voucher_value`, `voucher_expiry`)."""
    return (voucher_box(code, amount, expiry, code_label=t["voucher_code_label"],
                        value_label=t["voucher_value"], expiry_label=t["voucher_expiry"])
            + f"\n  <p>{use_html}</p>")


def notice(text_html, *, bg="#fff7ed", border="#fed7aa"):
    """Riquadro di avviso a una riga (arancio per default)."""
    return (f'<div style="padding:16px;background:{bg};border:1px solid {border};border-radius:8px;margin:20px 0">\n'
            f'    <p style="margin:0">{text_html}</p>\n  </div>')


# ---- alert admin -----------------------------------------------------------------

_CELL = "padding:8px 12px;border-bottom:1px solid #eee"


def row(label, value_html, *, width="", mono=False, last=False):
    """Riga della tabella di `admin_alert`: etichetta in grassetto e valore."""
    cell = "padding:8px 12px" if last else _CELL
    w = f";width:{width}" if width else ""
    v = ";font-family:monospace;font-size:12px;color:#555" if mono else ""
    return (f'<tr><td style="{cell}{w}"><strong>{label}</strong></td>'
            f'<td style="{cell}{v}">{value_html}</td></tr>')


def kv(label, value_html):
    """Riga semplice di `admin_panel` (tabella con cellpadding)."""
    return f"<tr><td><strong>{label}</strong></td><td>{value_html}</td></tr>"


def _bar(title, color, subtitle_html=""):
    sub = (f'\n    <p style="margin:6px 0 0;opacity:.9;font-size:13px">{subtitle_html}</p>'
           if subtitle_html else "")
    return (f'<div style="background:{color};color:#fff;padding:16px 20px;border-radius:8px 8px 0 0">\n'
            f'    <h2 style="margin:0;font-size:18px">{title}</h2>{sub}\n  </div>')


def admin_alert(title, color, *, subtitle_html="", lead_html="", rows_html="",
                after_html="", note_html="", max_width=680):
    """Alert admin: barra colorata, riquadro introduttivo opzionale, tabella
    di `row(...)`, blocchi aggiuntivi, nota finale in grigio."""
    lead = (f'\n  <div style="background:#fff;border:1px solid #ddd;border-top:none;padding:14px 16px;'
            f'font-size:13px;color:#334155">{lead_html}</div>' if lead_html else "")
    table = (f'\n  <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #ddd;'
             f'border-top:none;font-size:14px">\n    {rows_html}\n  </table>' if rows_html else "")
    after = f"\n  {after_html}" if after_html else ""
    note = (f'\n  <p style="color:#888;font-size:12px;margin-top:16px">{note_html}</p>' if note_html else "")
    return (f'<div style="{FONT};max-width:{max_width}px;margin:0 auto;padding:20px">\n'
            f'  {_bar(title, color, subtitle_html)}{lead}{table}{after}{note}\n</div>')


def admin_panel(title, color, body_html, *, max_width=640):
    """Alert admin a testo libero: barra colorata + riquadro bianco."""
    return (f'<div style="{FONT};max-width:{max_width}px;margin:0 auto">\n'
            f'  {_bar(title, color)}\n'
            f'  <div style="background:#fff;border:1px solid #ddd;border-top:none;padding:16px 20px;font-size:14px">\n'
            f'    {body_html}\n  </div>\n</div>')


def panel_table(rows_html):
    """Tabella compatta di `kv(...)` dentro `admin_panel`."""
    return (f'<table cellpadding="6" style="border-collapse:collapse;font-size:.95em">\n'
            f'      {rows_html}\n    </table>')


def callout(text_html, color="#d97706", bg="#fff4e5"):
    """Paragrafo evidenziato con bordo a sinistra (dentro `admin_panel`)."""
    return (f'<p style="background:{bg};padding:10px;border-left:4px solid {color};margin-top:14px">'
            f'{text_html}</p>')


def digest_page(title, subtitle, body_html, notes=()):
    """Pagina dei digest admin: header a gradiente, corpo, note in grigio."""
    note_html = "".join(
        f'\n<p style="color:#999;font-size:12px;{"margin-top:16px;" if i == 0 else ""}padding:0 4px">{n}</p>'
        for i, n in enumerate(notes))
    return (f'<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
            f'<body style="{FONT};color:#333;max-width:900px;margin:0 auto;padding:20px">\n'
            f'<div style="background:linear-gradient(135deg,#1a3c5e,#2c5f8a);color:white;padding:20px 24px;'
            f'border-radius:12px 12px 0 0">\n'
            f'<h2 style="margin:0">{title}</h2>\n'
            f'<p style="margin:8px 0 0;opacity:.85">{subtitle}</p>\n</div>\n'
            f'{body_html}{note_html}\n</body></html>')
