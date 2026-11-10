FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=4
# fonts-liberation: docling-parse renders non-embedded PDF fonts (Arial, Times New Roman) with system fonts; without
# them the layout model sees empty glyph boxes and the legal structure falls apart (tests/test_page_rendering.py)
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 fonts-liberation && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY requirements.lock ./
RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
COPY schemas ./schemas
RUN pip install --no-cache-dir --no-deps -e . && pip check
CMD ["python", "-m", "uvicorn", "odos.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
