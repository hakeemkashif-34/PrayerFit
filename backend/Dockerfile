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

# Don't run as root inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# 0.0.0.0 so the server is reachable from outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
