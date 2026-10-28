# Production image. Deployed instances build it in CodeBuild from a commit on
# GitHub (see infra/terraform).

# ECR Public mirror of Docker Hub's image (no pull rate limits).
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pango and HarfBuzz for weasyprint (PDF reports), openssl for the entrypoint.
# Every Python dependency has a wheel, so no compiler.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b openssl \
    && rm -rf /var/lib/apt/lists/*

# RDS certificate authorities, so the app can verify the database server.
ADD https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /etc/ssl/certs/rds-global-bundle.pem
RUN chmod 644 /etc/ssl/certs/rds-global-bundle.pem

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --system --uid 10001 --no-create-home cloze
USER cloze

EXPOSE 8000

# HTTPS on 8000, with a certificate the entrypoint generates at start.
ENTRYPOINT ["sh", "/app/scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--certfile", "/tmp/tls/cert.pem", "--keyfile", "/tmp/tls/key.pem", \
     "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "llm_chat:create_app()"]
