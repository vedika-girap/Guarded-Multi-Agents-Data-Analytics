# Start from the audited Python runtime; change this base only when the app's Python support changes.
FROM python:3.12-slim

# Run commands and serve the application from /app; change this path together with the copy paths below.
WORKDIR /app

# Keep Python output visible in container logs and avoid writing bytecode; adjust only for a deliberate runtime policy change.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install dependencies before application files so dependency layers remain cached across code changes.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create writable runtime storage and a non-root account; update these paths if the app's data location changes.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/chroma \
    && chown -R appuser:appuser /app/data

# Copy only application code; add other required source directories here if the runtime starts using them.
COPY app ./app
COPY scripts ./scripts
COPY docs/context ./docs/context

# Drop root privileges for application startup and runtime data writes; change only with a reviewed permission need.
USER appuser

# Document the HTTP port; change this when the application listener port changes.
EXPOSE 8000

# Probe the built-in health endpoint with Python's standard library; adjust the path if the health route changes.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=2)" || exit 1

# Serve on all container interfaces and honor PORT, defaulting to 8000; change the module or port policy with the app entry point.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
