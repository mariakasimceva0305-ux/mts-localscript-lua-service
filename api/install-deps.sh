#!/bin/sh
set -eu

has_wheels=0
if ls /tmp/wheels/*.whl >/dev/null 2>&1; then
  has_wheels=1
fi

if [ "$has_wheels" -eq 1 ]; then
  echo "[install-deps] Установка из локальных wheel в /tmp/wheels (без обращения к PyPI)"
  pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r requirements.txt
else
  echo "[install-deps] Установка с индекса: ${PIP_INDEX_URL}"
  pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host mirror.yandex.ru \
    --trusted-host mirrors.aliyun.com \
    --trusted-host mirrors.cloud.tencent.com \
    --trusted-host pypi.python.org \
    --default-timeout=180 \
    --retries 8 \
    --prefer-binary \
    -r requirements.txt
fi
