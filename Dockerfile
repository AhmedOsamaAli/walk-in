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
COPY web ./web
COPY --from=frontend /frontend/dist ./frontend/dist

RUN useradd --create-home --uid 10001 blankspace \
    && mkdir -p /srv/.cache \
    && chown -R blankspace /srv/.cache
USER blankspace

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
