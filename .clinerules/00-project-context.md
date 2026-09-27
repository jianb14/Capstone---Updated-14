# Project Context — Balloorina (Capstone)

## Overview
- Event styling / party decorations web application ("Balloorina").
- Django 5.0.6 monolith: single project (`Project/`) + single main app (`app/`).
- Deployed on Vercel (`vercel.json`) with WhiteNoise + Gunicorn; media via Cloudinary.

## Stack (do NOT introduce new frameworks/libraries without asking first)
- Backend: Django 5.0.6, Pillow, requests, python-dotenv, openai, pydantic, httpx
- Storage/DB: django-cloudinary-storage, dj-database-url, psycopg2-binary, cloudinary
- PDF/Excel exports: reportlab, xhtml2pdf, openpyxl
- Frontend: server-rendered Django templates + vanilla JS/CSS (no React/Vue/bundlers)

## Project Layout
- `Project/settings.py` — single settings file; INSTALLED_APPS is minimal.
- `app/models.py` — monolithic; organized into numbered sections with emoji headers
  (e.g. `# 2️⃣b Booking Status Log`). Preserve this sectioning when adding models.
- `app/views/` — views split by domain: admin.py, auth.py, bookings.py, chat.py,
  common.py, designs.py, notifications.py, payments.py, profiles.py, public.py.
- `app/templates/` — subfolders: admin/, auth/, client/, components/.
- `app/static/` and `static/` — css/, js/, images/, docs/.
- `app/services.py` — service/business-logic layer.
- Tests live at `app/` root as `test_*.py` files (e.g. `test_booking_tracker.py`).

## Environment & Secrets
- Local dev uses `.venv/` (Windows). Activate before running manage.py commands.
- Secrets come from `.env` via python-dotenv (see `.env.example`). `.env` is gitignored —
  NEVER commit secrets or hardcode API keys in code.
- Platform is Windows/PowerShell — write shell commands accordingly.

## Domain Models (key ones)
Booking (+BookingImage, BookingStatusLog, BlockedDate), Design, Payment (GCash flow,
GCashConfig), Review (+ReviewImage, ReviewReply), ChatSession/ChatMessage (+reactions,
notifications, quick replies, AI image feedback), Gallery/Canvas assets, Home/About/
Service content models (CMS-style singletons), SiteSettings (singleton).
