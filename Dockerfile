# The React app is built with Node, then served by the Python image; Node is not in the final image.
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=frontend /frontend/dist ./frontend/dist

RUN useradd --create-home --uid 10001 walkin \
    && mkdir -p /srv/.cache /srv/.data \
    && chown -R walkin /srv/.cache /srv/.data
USER walkin

EXPOSE 8000
# Render's proxy terminates HTTPS; trusting its X-Forwarded-Proto lets the app see https (secure cookies, absolute URLs).
# Only that proxy can reach the container, so any forwarding address is trusted.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
