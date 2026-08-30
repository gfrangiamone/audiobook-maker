# TTS Optimization Prompts — Multilingual Suite

Production-ready prompts for optimizing text for Text-to-Speech (TTS) synthesis. One prompt per supported language, derived from a single master specification.

## When to use which file

| Input language | Use this prompt | Notes |
|---|---|---|
| Italian | `prompt_tts_it.md` | |
| English (US/UK/AU) | `prompt_tts_en.md` | |
| Spanish (ES/LATAM) | `prompt_tts_es.md` | |
| French (FR/CA) | `prompt_tts_fr.md` | |
| German (DE/AT/CH) | `prompt_tts_de.md` | |
| Chinese (Mandarin, Simplified or Traditional) | `prompt_tts_zh.md` | Polyphone-based, not accent-based |
| Hindi (हिन्दी, Devanagari) | `prompt_tts_hi.md` | Devanagari-aware; Hinglish handling included |
| Russian (Русский, Cyrillic) | `prompt_tts_ru.md` | Stress marks for homographs; ё-restoration |
| Mixed-language documents | `prompt_tts_master.md` | Use only when ≥30% of the text is in a second language; otherwise use the dominant-language prompt |
| **Any other language** | `prompt_tts_generic.md` | **Fallback for languages without a dedicated prompt.** Includes self-confidence calibration: applies only safe structural rules at lower confidence levels. |

## Files in this folder

- **`prompt_tts_master.md`** — Governance document. Contains the full multilingual specification, with all six languages covered. Use for reference, audits, and when adding/changing rules. **Not recommended for production runs on monolingual texts**: too long, dilutes enforcement on weaker models.

- **`prompt_tts_<lang>.md`** (six files) — Production prompts. Each is self-contained and tuned for a single input language. ~150–180 lines each, optimized to stay within the working memory of non-reasoning LLMs.

## Why per-language prompts

Empirical testing on a non-reasoning model showed measurable enforcement degradation when the master multilingual prompt (~250 lines) was used on a monolingual Italian text vs. an Italian-only prompt of equivalent rule coverage but ~160 lines. The longer prompt caused the model to skip semicolon replacement, long-sentence splitting, and corrupted-title reconstruction — rules it had previously applied with a leaner Italian-focused prompt.

The master remains useful as the single source of truth: when a rule is updated, update the master first, then propagate the change to the affected language prompts.

## Routing strategy

In your orchestration layer, the language detection step should follow this fallback chain:

1. Detect the input language from the first 200–300 characters (any reasonable language detector — fastText, langdetect, the first message of the LLM itself).
2. If the detected language is one of the eight supported languages, use the corresponding language-specific prompt.
3. If the detector returns a language **not** in the supported list, use `prompt_tts_generic.md`.
4. If the detector is uncertain (low confidence score) or the text appears to mix two non-dominant languages, use `prompt_tts_generic.md` — its built-in self-calibration handles uncertainty more gracefully than forcing a wrong language-specific prompt.

The generic prompt is a fallback, not a substitute. A dedicated language prompt always outperforms it on the languages it covers, because the generic prompt deliberately holds back linguistic interventions when confidence is uncertain.

## How to integrate

In your orchestration layer:

1. Detect the input language from the first 200–300 characters.
2. Look up the corresponding prompt file from the table above; fall back to `prompt_tts_generic.md` if no match.
3. Pass the prompt as system message and the text to optimize as user message.
4. Receive the optimized text and forward to the TTS engine.

## Maintenance

When changing a rule:
1. Edit `prompt_tts_master.md` first.
2. Identify which language prompts are affected (most rules are universal — Section A in the master).
3. Update each affected language prompt.
4. If the rule has universal applicability, also update `prompt_tts_generic.md`.
5. Re-run the regression test suite (a fixed input text per language with a known-good output) before deploying.

## Version

v1.4 — **Diacritic restoration.** New rule covering accents the source file has *lost*, as opposed to accents added to disambiguate a heteronym (the existing Section B). Motivated by listening tests where a TTS engine read `perche` as *perche* and `restò` written `resto` as *resto*: the engine reads what is written, so a stripped accent is a mispronunciation with certainty, not a risk. Three damage patterns are covered — apostrophe surrogate (`perche'`), bare vowel (`manana`, `deja`), and digraph surrogate (German `ueber`) — each with the counter-examples that must not be touched (`un po'`, Swiss German `Strasse`, English `hotel`, `Baedeker`). Added as `A16` in the master, rule `16` in `it`/`es`/`fr`/`pt`/`de`/`en`, and `B5` (HIGH confidence only) in `generic`. `ru` needed nothing: its `ё`-restoration rule is the Cyrillic form of the same problem and already frames itself as an exception to the conservatism principle. `zh` and `hi` are not applicable.

  Note that this rule is the semantic half of the problem only. Accents that are *present* but Unicode-decomposed (NFD: `e` + U+0301 instead of `é`) look identical on screen, survive any LLM pass unchanged, and are still mispronounced. That is a normalization job for the ingestion code, not for a prompt.

v1.3 — `prompt_tts_en.md` revised based on regression test feedback. Four targeted improvements with explicit WRONG/RIGHT examples: (1) word-pronounced acronyms (UNESCO, NATO etc.) protected from over-application of dot-separation rule, (2) news agency tag removal made explicit with example, (3) heteronym marking promoted to default behaviour with worked examples on `read`/`lead`/`record`/`wind`, (4) em-dash → comma replacement linked to grammar check to prevent orphan fragments. File grew from 144 to 186 lines. Other language prompts unchanged.

v1.2 — Added generic fallback prompt for any language not specifically supported. Includes self-confidence calibration (HIGH/MEDIUM/LOW) that scopes interventions appropriately. Routing strategy documented.

v1.1 — Added Hindi and Russian. Eight languages total: Italian, English, Spanish, French, German, Chinese, Hindi, Russian.

v1.0 — Initial release. Six languages: Italian, English, Spanish, French, German, Chinese.
