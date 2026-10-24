# Image for the FastAPI backend. Slim keeps the image small.
FROM python:3.13-slim

# Don't write .pyc files, and print logs straight away instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install packages first, in their own layer. Docker caches this step,
# so rebuilding after a code change doesn't reinstall everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

# Don't run as root inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Bring the database up to date first, then start the server.
# 0.0.0.0 so the server is reachable from outside the container.
# --root-path /api because nginx serves the API under /api, so /api/docs works.
# The worker service uses this same image with its own command.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --root-path /api"]
