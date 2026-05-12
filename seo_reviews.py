"""SEO assets for the user reviews/feedback section.

Builds, per request, a JSON-LD block with AggregateRating + Review[] entries
and a visible HTML block listing the most recent approved reviews. These
together unlock Google review rich snippets (⭐ in SERP) and give AI search
engines (ChatGPT, Perplexity, Google AI Overview) citable, dated evidence
of real user feedback.

Cost: O(n) over approved reviews (the public list is capped at 50 server-side),
typically well under 1 ms — safe to run on every page request.
"""
from __future__ import annotations

import html as _html
import json as _json
from datetime import datetime, timezone

import community_store


# Visible heading per UI language
_REVIEWS_HEADING = {
    "it": "Recensioni degli Utenti",
    "en": "User Reviews",
    "fr": "Avis des Utilisateurs",
    "es": "Reseñas de Usuarios",
    "de": "Nutzerbewertungen",
    "zh": "用户评价",
}
_AVG_LABEL = {
    "it": "Media", "en": "Average", "fr": "Moyenne",
    "es": "Media", "de": "Durchschnitt", "zh": "平均",
}
_BASED_ON = {
    "it": "su {n} recensioni",
    "en": "based on {n} reviews",
    "fr": "sur {n} avis",
    "es": "basado en {n} reseñas",
    "de": "basierend auf {n} Bewertungen",
    "zh": "基于 {n} 条评价",
}
_NO_REVIEWS = {
    "it": "Ancora nessuna recensione.",
    "en": "No reviews yet.",
    "fr": "Aucun avis pour le moment.",
    "es": "Aún no hay reseñas.",
    "de": "Noch keine Bewertungen.",
    "zh": "暂无评价。",
}
_ANON = {
    "it": "Anonimo", "en": "Anonymous", "fr": "Anonyme",
    "es": "Anónimo", "de": "Anonym", "zh": "匿名",
}

# Visible block + JSON-LD review[] cap. Higher counts bloat the page without
# extra ranking benefit (Google only previews ~3-5 in rich results).
_MAX_REVIEWS = 10


def _stars_html(rating: int) -> str:
    rating = max(0, min(5, int(rating or 0)))
    return ("★" * rating) + ("☆" * (5 - rating))


def _localized_comment(item: dict, lang: str) -> str:
    """Pick the comment text in the requested UI language; fall back to the
    original. Empty if the user left the comment blank (rating-only)."""
    i18n = item.get("comment_i18n") or {}
    text = (i18n.get(lang) or "").strip()
    if text:
        return text
    return (item.get("comment") or "").strip()


def build_reviews(lang: str) -> dict:
    """Build review SEO assets for the given UI language.

    Returns a dict with keys:
      - ld_block:   '<script type="application/ld+json">…</script>' string
                    containing AggregateRating + Review[]. Empty string if
                    there are no reviews (avoids zero-rating schema warnings).
      - html_block: visible <section id="reviews"> ready to inject before
                    </body>. Always rendered (empty-state message if needed).
      - latest_ts:  unix timestamp of the most recent approved review, or 0.
      - count:      number of approved reviews.
      - avg:        average rating rounded to 2 decimals (0.0 if none).
    """
    try:
        items = community_store.feedback().all(include_archived=False)
    except Exception:
        items = []
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)
    total = len(items)
    heading = _REVIEWS_HEADING.get(lang, _REVIEWS_HEADING["en"])

    if total == 0:
        empty = _NO_REVIEWS.get(lang, _NO_REVIEWS["en"])
        html_block = (
            f'<section id="reviews" class="seo-block">'
            f'<h2>{_html.escape(heading)}</h2>'
            f'<p>{_html.escape(empty)}</p>'
            f'</section>'
        )
        return {"ld_block": "", "html_block": html_block,
                "latest_ts": 0, "count": 0, "avg": 0.0}

    avg = round(sum(int(it.get("rating", 0)) for it in items) / total, 2)
    latest_ts = max(int(it.get("created_at", 0)) for it in items)
    anon_label = _ANON.get(lang, _ANON["en"])

    review_entries: list[dict] = []
    visible_items: list[dict] = []
    for it in items[:_MAX_REVIEWS]:
        r = max(1, min(5, int(it.get("rating", 0))))
        name = (it.get("name") or "").strip() or anon_label
        ts = int(it.get("created_at", 0))
        date_iso = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if ts else ""
        )
        body_text = _localized_comment(it, lang)
        # Review.name satisfies Google's "named element" check: without it,
        # Search Console reports the entity as "Elemento senza nome" even
        # when itemReviewed + reviewRating + author are all present.
        review_name = f"Audiobook Maker — {r}/5 by {name}"
        review_entries.append({
            "@type": "Review",
            "name": review_name,
            "itemReviewed": {
                "@type": "SoftwareApplication",
                "name": "Audiobook Maker",
                "applicationCategory": "MultimediaApplication",
                "operatingSystem": "Web",
            },
            "reviewRating": {
                "@type": "Rating", "ratingValue": r,
                "bestRating": 5, "worstRating": 1,
            },
            "author": {"@type": "Person", "name": name},
            "datePublished": date_iso,
            "reviewBody": body_text,
            "inLanguage": (it.get("comment_lang") or lang or "en"),
        })
        visible_items.append({
            "rating": r, "name": name, "date": date_iso, "body": body_text,
        })

    aggregate_doc = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Audiobook Maker",
        "url": "https://audiobook-maker.com/",
        "applicationCategory": "MultimediaApplication",
        "operatingSystem": "Web",
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": avg,
            "bestRating": 5,
            "worstRating": 1,
            "reviewCount": total,
            "ratingCount": total,
        },
        "review": review_entries,
    }
    ld_block = (
        '<script type="application/ld+json">'
        + _json.dumps(aggregate_doc, ensure_ascii=False)
        + "</script>"
    )

    avg_label = _AVG_LABEL.get(lang, _AVG_LABEL["en"])
    based_on = _BASED_ON.get(lang, _BASED_ON["en"]).format(n=total)
    summary_stars = _stars_html(int(round(avg)))

    items_html_parts = []
    for v in visible_items:
        body_esc = _html.escape(v["body"]) if v["body"] else ""
        date_html = (
            f'<time datetime="{v["date"]}" class="review-date">{v["date"]}</time>'
            if v["date"] else ""
        )
        body_html = f'<p class="review-body">{body_esc}</p>' if body_esc else ""
        items_html_parts.append(
            '<li class="review-item">'
            f'<div class="review-head">'
            f'<span class="stars" aria-label="{v["rating"]} / 5">'
            f'{_stars_html(v["rating"])}</span> '
            f'<span class="review-author">{_html.escape(v["name"])}</span>'
            f'{date_html}'
            f'</div>'
            f'{body_html}'
            '</li>'
        )

    items_html = "\n".join(items_html_parts)
    html_block = (
        '<section id="reviews" class="seo-block">'
        f'<h2>{_html.escape(heading)}</h2>'
        '<p class="reviews-summary">'
        f'<span class="stars" aria-hidden="true">{summary_stars}</span> '
        f'<strong>{_html.escape(avg_label)}: {avg} / 5</strong> '
        f'<span class="review-count">— {_html.escape(based_on)}</span>'
        '</p>'
        f'<ul class="reviews-list">{items_html}</ul>'
        '</section>'
    )

    return {
        "ld_block": ld_block,
        "html_block": html_block,
        "latest_ts": latest_ts,
        "count": total,
        "avg": avg,
    }


def llms_txt_summary() -> str:
    """One-line rating summary for inclusion in /llms.txt. Returns empty
    string if there are no reviews yet."""
    try:
        items = community_store.feedback().all(include_archived=False)
    except Exception:
        return ""
    if not items:
        return ""
    total = len(items)
    avg = round(sum(int(it.get("rating", 0)) for it in items) / total, 2)
    return f"User rating: {avg}/5 from {total} verified reviews."


def llms_txt_block() -> str:
    """Multi-line "User feedback" block for /llms.txt — adds up to three
    recent review excerpts with dates and ratings on top of the headline.

    AI assistants quoting this block get attributable, dated evidence they
    can cite back to a stable URL (the home page reviews section). Returns
    an empty string when there are no approved reviews so the section is
    cleanly omitted from llms.txt.
    """
    try:
        items = community_store.feedback().all(include_archived=False)
    except Exception:
        return ""
    if not items:
        return ""
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)
    total = len(items)
    avg = round(sum(int(it.get("rating", 0)) for it in items) / total, 2)
    lines = [f"- Aggregate rating: {avg}/5 from {total} verified reviews."]
    # Cap excerpts at 3 — enough to look authentic, short enough that AI
    # citation snippets aren't dominated by review noise.
    for it in items[:3]:
        ts = int(it.get("created_at", 0))
        date_iso = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if ts else "n/a"
        )
        r = max(1, min(5, int(it.get("rating", 0))))
        comment = (it.get("comment") or "").strip().replace("\n", " ")
        # Trim very long comments — llms.txt is a summary, not the archive.
        if len(comment) > 200:
            comment = comment[:197].rstrip() + "..."
        if comment:
            lines.append(f'- {date_iso} ({r}/5): "{comment}"')
        else:
            lines.append(f"- {date_iso} ({r}/5): (rating only)")
    return "\n".join(lines)
