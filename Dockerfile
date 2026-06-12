# msl-capture — Playwright + poppler + LibreOffice headless
FROM python:3.11-slim

# System deps: poppler (pdftoppm), LibreOffice headless, fonts,
# and Chromium runtime deps (explicit, avoids playwright --with-deps broken font packages on Bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto \
    fonts-noto-cjk \
    wget \
    ca-certificates \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (deps installed manually above — avoids broken font packages)
RUN playwright install chromium

COPY . .

ENV PORT=8080
EXPOSE 8080

# Shell form so Railway's $PORT env var expands correctly
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
