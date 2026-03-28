FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VENV_PATH=/opt/venv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && python -m venv "${VENV_PATH}" \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="${VENV_PATH}/bin:${PATH}"

COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    VENV_PATH=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN useradd --create-home --uid 1000 botuser \
    && mkdir -p /app/logs /app/data

COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN chown -R botuser:botuser /app /opt/venv

USER botuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('https://api.telegram.org/bot' + os.environ['TELEGRAM_BOT_TOKEN'] + '/getMe')" || exit 1

CMD ["python", "-m", "app.main"]
