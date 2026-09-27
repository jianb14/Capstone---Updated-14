---
paths:
  - "**/test_*.py"
  - "**/tests.py"
---
# Testing Rules

- Use Django's `TestCase` (existing convention), with a `setUp` that creates the
  needed users/data via the ORM — see `app/test_booking_tracker.py` for the pattern.
- New test files go at `app/` root named `test_<feature>.py`
  (e.g. `test_booking_tracker.py`, `test_services_widgets.py`).
- Test class naming: `<Feature>Tests` (e.g. `BookingTrackerTests`, `ThemeQuizApiTests`).
- Run tests with: `python manage.py test app` (activate `.venv` first on Windows).
- When fixing a bug, add a regression test that fails without the fix.
- Do not weaken or delete existing tests to make a change pass.
