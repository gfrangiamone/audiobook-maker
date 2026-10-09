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
"""
from env_utils import env_float

DEFAULT_USD_EUR_RATE = 0.86
DEFAULT_PAYPAL_FIXED_FEE_EUR = 0.34
DEFAULT_PAYPAL_PERCENT_FEE = 3.4


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
