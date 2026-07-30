FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY main.py .

# Persistent volume: SQLite DB (recovery codes, audit log, IP blocks,
# branding) and, from v2.0.0's GeoIP phase on, the MaxMind .mmdb files.
RUN mkdir -p /data

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
