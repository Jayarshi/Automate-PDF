FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRANSLATION_CONFIG=/app/config/default.yaml

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[api]'
COPY config ./config
COPY scripts ./scripts
RUN mkdir -p /app/models /app/data/review

EXPOSE 8080
CMD ["local-translate-api"]

