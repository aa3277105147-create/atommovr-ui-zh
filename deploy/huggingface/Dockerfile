FROM python:3.12-slim-bookworm

ARG ATOMMOVR_REPOSITORY=https://github.com/bernienlab/atommovr.git
ARG ATOMMOVR_COMMIT=cca2553985bb9d81b19cae9b83074df4816502f9

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    GRADIO_SERVER_NAME=0.0.0.0 \
    MPLBACKEND=Agg \
    ATOMMOVR_SOURCE=/opt/atommovr \
    ATOMMOVR_UI_STATE_DIR=/tmp/atommovr-ui \
    ATOMMOVR_QUEUE_MAX_SIZE=8 \
    NO_PROXY=localhost,127.0.0.1,0.0.0.0 \
    no_proxy=localhost,127.0.0.1,0.0.0.0

WORKDIR /app

# The Space bundle contains the UI requirements. atommovr is fetched at the
# audited commit so a rebuild does not silently select a different algorithm
# implementation.
COPY requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates git \
    && git init /opt/atommovr \
    && git -C /opt/atommovr remote add origin "${ATOMMOVR_REPOSITORY}" \
    && git -C /opt/atommovr fetch --depth 1 origin "${ATOMMOVR_COMMIT}" \
    && git -C /opt/atommovr checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/atommovr rev-parse HEAD)" = "${ATOMMOVR_COMMIT}" \
    && python -m pip install --no-cache-dir --requirement /app/requirements.txt \
    && python -m pip install --no-cache-dir --editable /opt/atommovr \
    && cd /opt/atommovr \
    && python -c "from atommovr.algorithms.source.PPSU_weight_matching import _get_lib; _get_lib()" \
    && rm -rf /opt/atommovr/.git /root/.cache/pip /var/lib/apt/lists/*

COPY app.py benchmark.py comparison.py scheduling.py simulator.py version.py /app/
COPY player.css player.html player.js /app/
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY 算法说明.md /app/算法说明.md

RUN useradd --create-home --uid 1000 user \
    && mkdir -p /tmp/atommovr-ui \
    && chown -R user:user /app /tmp/atommovr-ui

USER user
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import json,os,urllib.request; port=os.environ.get('PORT') or os.environ.get('GRADIO_SERVER_PORT') or '7860'; data=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/atommovr-health', timeout=3)); assert data['application']=='atommovr-ui'" || exit 1

CMD ["python", "/app/app.py", "--no-browser"]
