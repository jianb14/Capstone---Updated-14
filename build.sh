#!/bin/bash

# 1. Install dependencies
python3.12 -m pip install -r requirements.txt

# 2. Database Migrations (Para sa database mo)
python3.12 manage.py migrate --noinput

# 3. Collect Static Files (Para sa CSS/Images)
python3.12 manage.py collectstatic --noinput