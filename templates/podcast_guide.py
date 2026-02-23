"""
Podcast guide data — base64 images and per-language guide sections.

The actual JavaScript data is stored in:
    _fragments/podcast_guide_data.js

This file documents the structure for reference. The JS data contains:

Images (base64 encoded PNG):
    PG_IMG_A — Screenshot of Netlify dashboard (drag & drop deploy)
    PG_IMG_B — Screenshot of Netlify deploy result

Guide sections per language (it, en, fr, es, de, zh):
    Each language has:
    - intro: Introduction text explaining the podcast feature
    - img: Base64 image tag (used in guide steps)
    - sections: List of {title, body} objects for each guide step

About section per language:
    - link: Link text for the About button
    - title: Modal title
    - paras: List of paragraphs describing the project

To modify the podcast guide content, edit:
    templates/_fragments/podcast_guide_data.js
"""
