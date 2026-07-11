FROM node:22-alpine AS frontend-builder
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-builder /build/backend/static ./static
RUN chmod +x docker-entrypoint.sh && useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8101
ENTRYPOINT ["./docker-entrypoint.sh"]
