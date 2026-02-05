#!/bin/sh

if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    while ! nc -z $SQL_HOST $SQL_PORT; do
      sleep 0.1
    done

    echo "PostgreSQL started"
fi

cd nivasSaarthi

# remove previous migration files but keep __init__.py
# find . -path "*/migrations/*.py" -not -name "__init__.py" -type f -delete || true
# find . -path "*/migrations/*.pyc" -type f -delete || true
# find . -path "*/migrations/__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
python manage.py flush --no-input
python manage.py makemigrations
python manage.py migrate

exec "$@"
