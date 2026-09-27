---
paths:
  - "app/templates/**"
  - "app/static/**"
  - "static/**"
---
# Frontend Rules (Django templates + vanilla JS/CSS)

- Server-rendered Django templates only — no SPA frameworks, no npm/bundlers.
- Reusable markup goes in `app/templates/components/` and is included with `{% include %}`.
- Reuse existing block/extends structure of sibling templates (e.g. other pages under
  `client/` or `admin/`) instead of inventing a new base layout.
- CSS lives under `static/css/` (or `app/static/css/`); JS under `static/js/`.
  Vanilla JS only — match existing naming and IIFE/module patterns.
- Never inline API keys or secrets in templates or JS.
- Static asset references must use Django's `{% static %}` tag, not hardcoded paths.
- Long inline JS in templates is an existing pattern in this repo; if adding more than a
  few lines of new JS, prefer extracting to `static/js/`.
