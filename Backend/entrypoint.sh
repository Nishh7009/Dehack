#!/bin/sh

echo "Waiting for PostgreSQL..."

# Wait for PostgreSQL to be ready
while ! nc -z $POSTGRES_HOST $POSTGRES_PORT; do
  sleep 0.5
done

echo "PostgreSQL started"

cd nivasSaarthi

# find . -path "*/migrations/*.py" -not -name "__init__.py" -type f -delete || true
# find . -path "*/migrations/*.pyc" -type f -delete || true
# find . -path "*/migrations/__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
# NOTE: Removed 'flush --no-input' - it was deleting all data on every restart!
python manage.py makemigrations
python manage.py migrate

exec "$@"
