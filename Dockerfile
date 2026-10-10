FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY main.py .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Persistent volume: SQLite DB (recovery codes, audit log, IP blocks,
# branding) and, from v2.0.0's GeoIP phase on, the MaxMind .mmdb files.
RUN mkdir -p /data && chmod 755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# Docker cannot tell a serving container from one whose uvicorn died at
# startup while its process lingered — that is exactly how this service sat
# dead for 7 days showing `Up`, with `--restart unless-stopped` never firing
# because nothing ever exited. Asking the port itself is what tells them
# apart. No curl in the slim image, and none needed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Hands /data to PUID:PGID (default 1000:1000) and drops root before
# starting uvicorn — see docker-entrypoint.sh.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
