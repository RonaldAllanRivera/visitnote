# One image, two commands: the API runs it with gunicorn, the worker with arq.
# Identical dependencies and identical code in both, so a job cannot fail on a version
# skew that the API never sees.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg is needed by the worker for audio normalisation. It is installed in the shared
# base rather than a worker-specific stage to keep the two containers byte-identical.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies are installed from the manifest alone, before application code is
# copied, so a source change does not invalidate the dependency layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

# Non-root. The application writes nothing to disk except /tmp scratch for ffmpeg.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Overridden per service in compose; this default makes `docker run` useful.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
