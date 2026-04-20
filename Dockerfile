FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# OCR-ready runtime (opt-in feature becomes available in container)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ocr.txt

COPY . .

# Example:
#   docker run --rm -v "$PWD/samples:/data" knowledgeharness \
#     python app.py /data/demo.md --output-dir /data/out
CMD ["python", "app.py", "samples/demo.md", "--output-dir", "outputs"]
