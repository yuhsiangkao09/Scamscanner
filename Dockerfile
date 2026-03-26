FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_DEVICE=cpu \
    APP_RELOAD=false

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.cpu.txt ./requirements.cpu.txt

RUN pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 && \
    pip install --find-links https://data.pyg.org/whl/torch-2.5.1+cpu.html torch-scatter==2.1.2+pt25cpu && \
    pip install -r requirements.cpu.txt

COPY backend ./backend
COPY model.py ./model.py
COPY models ./models
COPY resources ./resources
COPY url_scanner_ui.html ./url_scanner_ui.html

RUN mkdir -p /app/logs/url_scanner_html \
    /app/logs/url_scanner_feedback_html \
    /app/logs/url_scanner_screenshots

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
