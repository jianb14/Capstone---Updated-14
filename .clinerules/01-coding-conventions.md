# Coding Conventions

- Python for all backend code; follow existing style — no linters/formatters are enforced,
  so match the surrounding code exactly.
- Keep functions small and place new code in the correct existing module
  (see project-context for the `app/views/` layout). Do not create new top-level
  script/scratch files in the repo root.
- Prefer Django idioms over hand-rolled logic: `get_object_or_404`, ORM queries,
  `request.POST.get(...)` with `.strip()`, `json.loads(request.body)` for JSON APIs.
- Never modify `db.sqlite3` directly or commit it. Do not touch `.env`.
- Media/uploads: images go through ImageField with an `upload_to=` path
  (e.g. `booking_references/`, `gallery/`).
- When editing a feature, check `app/chat_section.txt`-style extracted sections only as
  reference — real changes go in the actual `.py`/`.html` files.
- Git: commit messages in English, one logical change per commit.
