FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system opshub \
    && adduser --system --ingroup opshub opshub \
    && mkdir -p /data/exports \
    && chown -R opshub:opshub /app /data

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install .

USER opshub

EXPOSE 8787

CMD ["ops-hub-api"]
