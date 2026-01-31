#!/bin/bash
set -e

# 1. Run Migrations (Safe to run every time; checks for new changes)
echo "--- Running Database Migrations ---"
alembic upgrade head

# 2. Start Hypercorn using the Factory Pattern and Render's PORT
echo "--- Starting Hypercorn on port $PORT ---"
# We use app:create_app() instead of app:app to ensure clean initialization
exec hypercorn "app:create_app()" --bind 0.0.0.0:$PORT