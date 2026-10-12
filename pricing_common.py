"""pricing_common — cambio USD->EUR, commissioni PayPal e soglia gratuita.

Modulo foglia (stdlib + `env_utils`). Prima: `ABM_GEMINI_USD_EUR_RATE`
letto in quattro moduli (uno solo controllava i valori <= 0), il gross-up
PayPal scritto due volte (`gemini_tts`, `speechify_tts`), l'audit VoxCPM
che prendeva il cambio da `speechify_tts`.

- `usd_eur_rate()`: il cambio dichiarato; <= 0 o non numerico -> default.
- `paypal_fixed_fee_eur()`, `paypal_percent_fee()`: le fee da env.
- `paypal_gross_up(base_eur)`: prezzo lordo che lascia `base_eur` al netto
  della quota PayPal (fee fissa + percentuale a carico del cliente).
- `free_result(gross_eur, threshold_eur)`: le quattro chiavi comuni dei
  dict prezzo (`user_price_eur`, `list_price_eur`, `is_free`,
  `free_threshold_eur`).
- `CHARS_PER_TOKEN_BY_LANG`: caratteri per token
  per lingua (stima token del TTS Gemini); `TRANSLATION_TOKEN_WEIGHT`,
  `token_weight(language)`: peso di un carattere non latino rispetto al
  latino nel prezzo della traduzione, misurato sull'audit di prod.
"""
from env_utils import env_float

DEFAULT_USD_EUR_RATE = 0.86
DEFAULT_PAYPAL_FIXED_FEE_EUR = 0.34
DEFAULT_PAYPAL_PERCENT_FEE = 3.4

# Per-language token ratios (chars per token).
# Copre tutte le lingue ufficialmente supportate da Gemini TTS (vedi
# SUPPORTED_UI_LANGUAGES) + zh legacy. Latin ~4.0, Cyrillic ~3.0, CJK ~1.5,
# Indic/Arabic/Thai ~2.0.
CHARS_PER_TOKEN_BY_LANG = {
    "it": 4.0, "en": 4.0, "fr": 4.0, "es": 4.0, "de": 4.0, "pt": 4.0,
    "nl": 4.0, "pl": 4.0, "ro": 4.0, "tr": 4.0, "id": 4.0, "vi": 4.0,
    "ru": 3.0, "uk": 3.0,
    "zh": 1.5, "ja": 1.5, "ko": 1.5,
    "hi": 2.0, "ar": 2.0, "bn": 2.0, "mr": 2.0, "ta": 2.0, "te": 2.0, "th": 2.0,
    "default": 4.0,
}


# Peso di un carattere nel prezzo della traduzione, rispetto al latino.
# Misurato sull'audit di prod (translation_cost_audit, lug-ott 2026, job
# completati senza ottimizzazione, token reali): costo mediano per carattere
# della lingua sorgente diviso quello delle sorgenti latine verso la stessa
# destinazione (latino->en: 0.50 EUR/M car., n=18; le sorgenti qui sotto
# vanno tutte verso en). La tabella token del TTS (4.0/ratio) sbagliava per
# eccesso su russo (1.33) e hindi (2.0), per CJK e' confermata dai dati.
TRANSLATION_TOKEN_WEIGHT = {
    # ja->en 1.36 EUR/M = 2.7x (n=1, ja->de 2.39); stessa ratio 1.5 car/token
    # del TTS anche per zh/ko, senza job propri a pieno costo.
    "ja": CHARS_PER_TOKEN_BY_LANG["default"] / CHARS_PER_TOKEN_BY_LANG["ja"],
    "zh": CHARS_PER_TOKEN_BY_LANG["default"] / CHARS_PER_TOKEN_BY_LANG["zh"],
    "ko": CHARS_PER_TOKEN_BY_LANG["default"] / CHARS_PER_TOKEN_BY_LANG["ko"],
    "ru": 1.3,    # 0.64 EUR/M, n=3
    "uk": 1.3,    # nessun job: stessa scrittura cirillica del russo
    "hi": 1.65,   # 0.83 EUR/M, n=6
    "ar": 1.95,   # 0.98 EUR/M, n=4 (dispersione alta: 0.29-1.77)
    # Nessun job reale: tabella token del TTS (4.0/2.0), da ricalibrare
    # quando l'audit avra' campioni thai.
    "th": CHARS_PER_TOKEN_BY_LANG["default"] / CHARS_PER_TOKEN_BY_LANG["th"],
}

# Codici ISO 639-2/3 dei metadati EPUB/PDF -> codice a due lettere.
_ISO3_TO_ISO1 = {"jpn": "ja", "zho": "zh", "chi": "zh", "cmn": "zh",
                 "yue": "zh", "kor": "ko", "rus": "ru", "ukr": "uk",
                 "hin": "hi", "ara": "ar", "tha": "th"}


def token_weight(language):
    """Quanti caratteri latini vale un carattere di `language` nel prezzo
    della traduzione (TRANSLATION_TOKEN_WEIGHT; 1.0 per latine e
    sconosciute). Il codice arriva gia' normalizzato con `i18n.norm_lang`
    (questo modulo e' foglia); accetta anche i codici a tre lettere."""
    lang = language or ""
    lang = _ISO3_TO_ISO1.get(lang, lang)
    return max(1.0, TRANSLATION_TOKEN_WEIGHT.get(lang, 1.0))


def usd_eur_rate():
    """`ABM_GEMINI_USD_EUR_RATE` (la stessa variabile per Gemini, Speechify,
    VoxCPM, pagamenti e credito Cloudflare): un valore <= 0 o non numerico
    degrada al default invece di dividere per zero da qualche parte."""
    rate = env_float("ABM_GEMINI_USD_EUR_RATE", DEFAULT_USD_EUR_RATE)
    if not rate or rate <= 0:
        return DEFAULT_USD_EUR_RATE
    return rate


def paypal_fixed_fee_eur():
    return env_float("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", DEFAULT_PAYPAL_FIXED_FEE_EUR)


def paypal_percent_fee():
    return env_float("ABM_GEMINI_PAYPAL_PERCENT_FEE", DEFAULT_PAYPAL_PERCENT_FEE)


def paypal_gross_up(base_eur, *, fixed_fee_eur=None, percent_fee=None):
    """`(base + fee fissa) / (1 - fee%/100)`: il lordo da chiedere al cliente
    perche' dopo la quota PayPal resti `base_eur`. Solleva `ValueError` se la
    percentuale e' >= 100 (configurazione impossibile)."""
    fixed = paypal_fixed_fee_eur() if fixed_fee_eur is None else fixed_fee_eur
    pct = paypal_percent_fee() if percent_fee is None else percent_fee
    factor = 1.0 - (pct / 100.0)
    if factor <= 0:
        raise ValueError("PAYPAL_PERCENT_FEE >= 100, invalid config")
    return (base_eur + fixed) / factor


def free_result(gross_eur, threshold_eur):
    """Prezzo arrotondato al centesimo e sua gratuita' sotto soglia."""
    user_price = round(gross_eur, 2)
    is_free = user_price < threshold_eur
    return {
        "user_price_eur": 0.0 if is_free else user_price,
        "list_price_eur": user_price,
        "is_free": is_free,
        "free_threshold_eur": threshold_eur,
    }


def billable_text(ch, title_prefix=None, normalize=None):
    """Il testo che la voce legge per il capitolo `ch`, e che quindi si
    fattura: il titolo parlato che il piano antepone (`title_prefix(ch,
    text)`, separatore compreso) piu' il corpo. `normalize` (es. la
    normalizzazione Gemini) si applica a entrambi. "" per un capitolo
    senza testo. Unica regola per Gemini, Speechify e VoxCPM: prima i titoli
    letti erano fatturati solo su VoxCPM (un libro da 402 capitoli ne leggeva
    ~15 mila caratteri gratis)."""
    text = getattr(ch, "text", "") or ""
    if not text:
        return ""
    prefix = title_prefix(ch, text) if title_prefix else ""
    spoken = prefix + text
    return normalize(spoken) if normalize else spoken


def billable_chars(chapters, title_prefix=None, normalize=None):
    """(caratteri per capitolo, totale, testi fatturati) su `billable_text`."""
    texts = [billable_text(ch, title_prefix, normalize) for ch in chapters]
    per = [len(t) for t in texts]
    return per, sum(per), texts
