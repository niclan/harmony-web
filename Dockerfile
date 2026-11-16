FROM python:3.15-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/

EXPOSE 5000

ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

# Run with gunicorn (production WSGI server)
# - 2 workers (adjust based on CPU cores: 2 * cores + 1)
# - 4 threads per worker (handles async I/O to Harmony Hub)
# - 60s timeout (allows time for Harmony Hub responses)
# - Bind to 0.0.0.0 (Docker needs this, not localhost)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
