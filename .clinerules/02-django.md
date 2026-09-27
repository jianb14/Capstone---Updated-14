---
paths:
  - "app/**"
  - "Project/**"
  - "manage.py"
---
# Django Rules

## Models (`app/models.py`)
- Add new models inside the matching numbered section; create a new numbered section
  (e.g. `# 14️⃣ <Name>`) only for a genuinely new domain area.
- Always set `related_name` on ForeignKey/OneToOneField (existing convention).
- Use `on_delete=models.CASCADE` by default; `SET_NULL` with `null=True, blank=True`
  when the parent may be removed (see CanvasAsset.label_ref).
- Add `help_text` for non-obvious fields and `__str__` methods like the existing ones.
- CharFields for free text use `blank=True, default=''` (existing pattern).

## Views (`app/views/`)
- Always decorate with `@login_required` where auth is needed, and `@require_GET` /
  `@require_POST` for API endpoints.
- Enforce roles exactly like existing code:
  `if request.user.role not in ["admin", "staff"]: return HttpResponseForbidden("Not allowed")`
  (pure admin-only pages use `request.user.role != "admin"`).
- JSON endpoints: parse `json.loads(request.body)` inside `try/except`, return
  `JsonResponse`; keep the existing response shape.
- Log sensitive actions with `log_action(request.user, "...")` where already used.
- New URL patterns go in `app/urls.py`; follow the existing naming
  (`admin_<thing>_<action>`, `chat_<action>`, etc.).

## Migrations
- After changing models, run `python manage.py makemigrations app` and
  `python manage.py migrate`; never edit committed migrations by hand.
