FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY json_scrapers/ ./json_scrapers/
COPY data/ ./data/
RUN python -m backend.db_loader
COPY --from=frontend /build/frontend/build ./frontend/build/
COPY gunicorn.conf.py ./
RUN useradd --create-home app && chown -R app:app /app
USER app
EXPOSE 8080
CMD ["gunicorn", "--config", "gunicorn.conf.py", "backend.advisor:app"]
