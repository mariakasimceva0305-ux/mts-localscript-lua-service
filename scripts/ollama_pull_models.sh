#!/bin/sh
# Одноразовый bootstrap: подтягивает модели в общий volume Ollama через HTTP API демона.
# Запускается в контейнере ollama/ollama (есть CLI), OLLAMA_HOST указывает на сервис ollama.
set -eu

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
export OLLAMA_HOST

MODEL="${MODEL_NAME:-qwen2.5-coder:7b}"
FB="${FALLBACK_MODEL:-deepseek-coder:6.7b}"

echo "================================================================"
echo "[ollama-pull] Старт: $(date)"
echo "[ollama-pull] OLLAMA_HOST=${OLLAMA_HOST}"
echo "[ollama-pull] MODEL_NAME=${MODEL} FALLBACK_MODEL=${FB}"
echo "[ollama-pull] Диагностика: docker compose logs -f ollama  (если демон не отвечает)"
echo "================================================================"

# Дождаться ответа демона (healthcheck compose уже прошёл, но даём запас по гонкам)
i=0
max=120
while ! ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge "$max" ]; then
    echo "[ollama-pull] ERROR: Ollama недоступен по ${OLLAMA_HOST} за ${max} с."
    echo "[ollama-pull] Проверьте: сервис ollama в статусе healthy, сеть compose, логи: docker compose logs ollama"
    exit 1
  fi
  if [ "$((i % 15))" -eq 0 ]; then
    echo "[ollama-pull] Ожидание Ollama... ${i}/${max} с"
  fi
  sleep 1
done

echo "[ollama-pull] Ollama отвечает. Pull идемпотентен; первый старт может занять много времени и места на диске."

pull_one() {
  _m="$1"
  echo "[ollama-pull] --- ollama pull ${_m} ---"
  if ollama pull "${_m}"; then
    echo "[ollama-pull] OK: ${_m}"
    return 0
  fi
  echo "[ollama-pull] FAILED: ${_m} (сеть, registry, место на диске или опечатка в имени модели)"
  return 1
}

set +e
pull_one "${MODEL}"
PRIM_RC=$?
pull_one "${FB}"
FB_RC=$?
set -e

if ollama show "${MODEL}" >/dev/null 2>&1; then
  echo "[ollama-pull] READY: основная модель доступна: ${MODEL}"
  ollama list
  exit 0
fi

if ollama show "${FB}" >/dev/null 2>&1; then
  echo "[ollama-pull] READY: основная недоступна (pull rc=${PRIM_RC}), работает запасная: ${FB}"
  ollama list
  exit 0
fi

echo "[ollama-pull] ERROR: ни основная (${MODEL}), ни запасная (${FB}) не доступны после pull."
echo "[ollama-pull] rc: primary=${PRIM_RC} fallback=${FB_RC}"
echo "[ollama-pull] Проверьте MODEL_NAME/FALLBACK_MODEL, свободное место и docker compose logs ollama-pull"
ollama list || true
exit 1
