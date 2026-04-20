#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_ROOT="${ROOT_DIR}/bing-github-action/artifacts"
TIMESTAMP="$(TZ=Asia/Shanghai date '+%Y-%m-%d-%H-%M-%S')"
RUN_DIR="${ARTIFACT_ROOT}/${TIMESTAMP}"
LOG_FILE="${RUN_DIR}/bing-run.log"
RUN_META="${RUN_DIR}/run-meta.txt"

QL_DIR="${QL_DIR:-/Users/songmiao/ql}"
SCRIPT_PATH="${BING_SCRIPT_PATH:-${QL_DIR}/data/scripts/bingRewards_v1.0.7.py}"
PYTHON_BIN="${BING_PYTHON_BIN:-${QL_DIR}/data/deps/bing_rewards_venv/bin/python3}"
DEBUG_DIR="${BING_DEBUG_DIR:-${QL_DIR}/data/scripts/debug}"
CONFIG_SH="${QL_CONFIG_SH:-${QL_DIR}/data/config/config.sh}"

mkdir -p "${RUN_DIR}"

{
  echo "timestamp=${TIMESTAMP}"
  echo "runner_host=$(hostname)"
  echo "runner_user=$(whoami)"
  echo "ql_dir=${QL_DIR}"
  echo "script_path=${SCRIPT_PATH}"
  echo "python_bin=${PYTHON_BIN}"
  echo "debug_dir=${DEBUG_DIR}"
} > "${RUN_META}"

for path in "${QL_DIR}" "${SCRIPT_PATH}" "${PYTHON_BIN}"; do
  if [ ! -e "${path}" ]; then
    echo "missing required path: ${path}" | tee -a "${RUN_META}" >&2
    exit 1
  fi
done

export TZ="${TZ:-Asia/Shanghai}"
export BING_SKIP_DEVICE_SECURITY="${BING_SKIP_DEVICE_SECURITY:-1}"
export GITHUB_ACTIONS_BING=1
export BING_GITHUB_ARTIFACT_DIR="${RUN_DIR}"

before_debug="$(mktemp)"
after_debug="$(mktemp)"
cleanup() {
  rm -f "${before_debug}" "${after_debug}"
}
trap cleanup EXIT

if [ -d "${DEBUG_DIR}" ]; then
  find "${DEBUG_DIR}" -maxdepth 1 -type f -print | sort > "${before_debug}"
else
  : > "${before_debug}"
fi

if [ -f "${CONFIG_SH}" ]; then
  set +u
  set -a
  # shellcheck disable=SC1090
  source "${CONFIG_SH}" >/dev/null 2>&1 || true
  set +a
  set -u
fi

echo "[bing-action] start ${TIMESTAMP}" | tee -a "${RUN_META}"
echo "[bing-action] script=${SCRIPT_PATH}" | tee -a "${RUN_META}"

set +e
"${PYTHON_BIN}" "${SCRIPT_PATH}" 2>&1 | tee "${LOG_FILE}"
exit_code=${PIPESTATUS[0]}
set -e

echo "exit_code=${exit_code}" >> "${RUN_META}"

if [ -d "${DEBUG_DIR}" ]; then
  find "${DEBUG_DIR}" -maxdepth 1 -type f -print | sort > "${after_debug}"
  mkdir -p "${RUN_DIR}/debug"
  comm -13 "${before_debug}" "${after_debug}" | while IFS= read -r file; do
    [ -n "${file}" ] || continue
    cp -f "${file}" "${RUN_DIR}/debug/" || true
  done
fi

LATEST_QL_LOG_DIR="${QL_DIR}/data/log/$(basename "${SCRIPT_PATH}" .py)"
if [ -d "${LATEST_QL_LOG_DIR}" ]; then
  latest_log="$(find "${LATEST_QL_LOG_DIR}" -type f -name '*.log' | sort | tail -n 1)"
  if [ -n "${latest_log}" ] && [ -f "${latest_log}" ]; then
    cp -f "${latest_log}" "${RUN_DIR}/latest-ql.log" || true
  fi
fi

exit "${exit_code}"
