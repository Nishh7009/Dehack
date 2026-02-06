#!/bin/sh

echo "Waiting for PostgreSQL..."

# Wait for PostgreSQL to be ready
while ! nc -z $POSTGRES_HOST $POSTGRES_PORT; do
  sleep 0.5
done

echo "PostgreSQL started"

cd nivasSaarthi

# remove previous migration files but keep __init__.py
# find . -path "*/migrations/*.py" -not -name "__init__.py" -type f -delete || true
# find . -path "*/migrations/*.pyc" -type f -delete || true
# find . -path "*/migrations/__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
python manage.py flush --no-input
python manage.py makemigrations
python manage.py migrate

exec "$@"
