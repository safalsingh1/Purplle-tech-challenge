FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV (headless — no X11 needed on Railway)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install API dependencies (including CPU-only PyTorch and ultralytics for live overlays)
RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    "uvicorn[standard]>=0.27.0" \
    sqlalchemy>=2.0.0 \
    pydantic>=2.0.0 \
    httpx>=0.27.0 \
    numpy>=1.24.0 \
    opencv-python-headless>=4.8.0

# Install CPU PyTorch first to keep image small, then ultralytics
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir ultralytics>=8.0.0


# Copy application code
COPY app/ ./app/
COPY data/ ./data/

# Create data directories
RUN mkdir -p data/camera_clips

# Environment defaults
ENV DATABASE_URL=sqlite:///./data/store_intelligence.db
ENV POS_CSV_PATH=data/pos_transactions.csv
ENV PORT=8000

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen('http://localhost:' + os.getenv('PORT', '8000') + '/health')" || exit 1

# Start the API
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
