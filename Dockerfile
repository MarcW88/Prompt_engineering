FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY analysis ./analysis
COPY config ./config
COPY filters ./filters
COPY models ./models
COPY scrapers ./scrapers
COPY sources ./sources
COPY storage ./storage
COPY utils ./utils
COPY collection_worker.py .

ENTRYPOINT ["python", "collection_worker.py"]
CMD ["--once"]
