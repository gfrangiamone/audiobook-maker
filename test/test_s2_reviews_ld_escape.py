"""S2 (2026-10-12): nome e commento dei feedback pubblici finiscono nel JSON-LD
della home. `json.dumps` lascia `<` e `>` intatti: con `</script` nel nome lo
script si chiudeva e il resto diventava HTML eseguito da ogni visitatore.
Ora passa da `seo_ld.ld_json`, che escapa `<`, `>`, `&` come `\\uXXXX`."""
import json

import community_store
import seo_ld
import seo_reviews

EVIL = '</script><img src=x onerror=alert(1)>'


class _Feedback:
    def __init__(self, items):
        self._items = items

    def all(self, include_archived=False):
        return list(self._items)


def test_ld_json_neutralizes_every_html_delimiter():
    s = seo_ld.ld_json({"t": "a</script><!-- b --> & c d"})
    inner = s
    assert "<" not in inner and ">" not in inner and "&" not in inner and " " not in inner
    assert json.loads(s)["t"] == "a</script><!-- b --> & c d"
    assert "ü" in seo_ld.ld_json({"t": "ü"})                    # niente escape ASCII


def test_feedback_name_and_comment_cannot_close_the_script(monkeypatch):
    items = [{"name": EVIL, "rating": 5, "created_at": 1_700_000_000,
              "comment_i18n": {"en": "great <!-- x --> & </script>"}}]
    monkeypatch.setattr(community_store, "feedback", lambda: _Feedback(items))
    out = seo_reviews.build_reviews("en")
    ld = out["ld_block"]
    head, tail = '<script type="application/ld+json">', "</script>"
    assert ld.startswith(head) and ld.endswith(tail)
    inner = ld[len(head):-len(tail)]
    assert "<" not in inner and ">" not in inner and "&" not in inner
    doc = json.loads(inner)
    assert doc["review"][0]["author"]["name"] == EVIL           # il dato resta fedele
    assert doc["review"][0]["reviewBody"] == "great <!-- x --> & </script>"
    assert EVIL not in out["html_block"] and "&lt;/script&gt;" in out["html_block"]
