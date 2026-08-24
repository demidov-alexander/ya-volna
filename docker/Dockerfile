# Minimal one-shot image (spec section 21).
#   docker build -t ya-volna -f docker/Dockerfile .
#   docker run --rm --env-file .env \
#     -v "$PWD/config.yaml:/app/config.yaml:ro" -v "$PWD/data:/app/data" ya-volna generate
FROM python:3.14-slim AS build

WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m venv /opt/venv && /opt/venv/bin/pip install .

FROM python:3.14-slim

# Non-root runtime user; /app/data is the only writable path.
RUN useradd --create-home --uid 10001 yavolna
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
RUN mkdir -p /app/data && chown -R yavolna:yavolna /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER yavolna
VOLUME ["/app/data"]

# No secrets are baked in: the token comes from the environment at run time.
ENTRYPOINT ["yavolna"]
CMD ["generate", "--dry-run"]
