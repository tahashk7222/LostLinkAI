FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
# Derive the learned image model at build time (needs network). Runs as root because /app is root-owned;
# the app user only reads the file. Fails the build if the checksum does not match.
RUN python -m scripts.fetch_vision_model
RUN useradd --create-home appuser && mkdir -p /data/storage && chown -R appuser /data
USER appuser

ENV STORAGE_DIR=/data/storage
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
