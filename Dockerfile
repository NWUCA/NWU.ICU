FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    SUPERCRONIC=supercronic-linux-amd64 \
    SUPERCRONIC_SHA1SUM=cd48d45c4b10f3f0bfdd3a57d054cd05ac96812b

# pip also carries a CA bundle; install the fixed official wheel by hash.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget \
    && update-ca-certificates \
    && wget -O /tmp/pip-26.2.2-py3-none-any.whl \
       https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl \
    && echo "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70  /tmp/pip-26.2.2-py3-none-any.whl" | sha256sum -c - \
    && /usr/local/bin/python -m pip install --no-cache-dir --no-index --no-deps --upgrade /tmp/pip-26.2.2-py3-none-any.whl \
    && rm /tmp/pip-26.2.2-py3-none-any.whl \
    && wget "$SUPERCRONIC_URL" \
    && echo "${SUPERCRONIC_SHA1SUM}  ${SUPERCRONIC}" | sha1sum -c - \
    && chmod +x "$SUPERCRONIC" \
    && mv "$SUPERCRONIC" "/usr/local/bin/supercronic" \
    && apt-get remove -y wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Reject stale system or Requests trust stores when rebuilding from cached bases.
RUN python -c "import hashlib, ssl; import certifi; \
    blocked = {'86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b', 'd7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4'}; \
    contexts = {'system': ssl.create_default_context(), 'certifi': ssl.create_default_context(cafile=certifi.where())}; \
    roots = {name: {hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)} for name, context in contexts.items()}; \
    assert all(certs and not certs.intersection(blocked) for certs in roots.values()), {name: sorted(certs.intersection(blocked)) for name, certs in roots.items()}; \
    print('CA trust verified: emSign G3 and AAA roots absent from system and certifi stores')"

COPY . .

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --no-log-init app \
    && mkdir -p /app/data /app/media /app/static /app/archive-cache \
    && chown -R app:app /app

USER app

ARG BACKEND_COMMIT=unknown
ARG BACKEND_GITHUB_URL=
LABEL org.opencontainers.image.source=$BACKEND_GITHUB_URL \
    org.opencontainers.image.revision=$BACKEND_COMMIT

EXPOSE 8000

CMD ["gunicorn", "settings.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
