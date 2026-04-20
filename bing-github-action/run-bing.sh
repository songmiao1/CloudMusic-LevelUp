#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION_DIR="${ROOT_DIR}/bing-github-action"
SCRIPT_DIR="${ACTION_DIR}/scripts"
RUNTIME_DIR="${ACTION_DIR}/runtime"
ARTIFACT_ROOT="${ACTION_DIR}/artifacts"
TIMESTAMP="$(TZ=Asia/Shanghai date '+%Y-%m-%d-%H-%M-%S')"
RUN_DIR="${ARTIFACT_ROOT}/${TIMESTAMP}"
LOG_FILE="${RUN_DIR}/bing-run.log"
RUN_META="${RUN_DIR}/run-meta.txt"

SCRIPT_PATH="${BING_SCRIPT_PATH:-${SCRIPT_DIR}/bingRewards.py}"
PYTHON_BIN="${BING_PYTHON_BIN:-python3}"
DEBUG_DIR="${BING_DEBUG_DIR:-${RUNTIME_DIR}/debug}"

mkdir -p "${RUN_DIR}" "${RUNTIME_DIR}" "${DEBUG_DIR}"

{
  echo "timestamp=${TIMESTAMP}"
  echo "runner_host=$(hostname)"
  echo "runner_user=$(whoami)"
  echo "script_path=${SCRIPT_PATH}"
  echo "python_bin=${PYTHON_BIN}"
  echo "runtime_dir=${RUNTIME_DIR}"
  echo "debug_dir=${DEBUG_DIR}"
} > "${RUN_META}"

for path in "${SCRIPT_PATH}" "${PYTHON_BIN}"; do
  if [ ! -e "${path}" ]; then
    echo "missing required path: ${path}" | tee -a "${RUN_META}" >&2
    exit 1
  fi
done

decode_secret_to_file() {
  local secret_value="$1"
  local target_file="$2"
  local mode="$3"
  local tmp_file

  tmp_file="$(mktemp)"
  if [ "${mode}" = "b64" ]; then
    printf '%s' "${secret_value}" | base64 --decode > "${tmp_file}"
  else
    printf '%s' "${secret_value}" > "${tmp_file}"
  fi
  mkdir -p "$(dirname "${target_file}")"
  mv "${tmp_file}" "${target_file}"
}

seed_runtime_from_secrets() {
  if [ -n "${BING_RUNTIME_SEED_TGZ_B64:-}" ] && [ ! -f "${RUNTIME_DIR}/.seed_runtime_applied" ]; then
    local seed_archive
    seed_archive="$(mktemp)"
    printf '%s' "${BING_RUNTIME_SEED_TGZ_B64}" | base64 --decode > "${seed_archive}"
    tar -xzf "${seed_archive}" -C "${RUNTIME_DIR}"
    rm -f "${seed_archive}"
    touch "${RUNTIME_DIR}/.seed_runtime_applied"
  fi

  if [ ! -s "${RUNTIME_DIR}/bing_accounts.json" ]; then
    if [ -n "${BING_ACCOUNTS_JSON_B64:-}" ]; then
      decode_secret_to_file "${BING_ACCOUNTS_JSON_B64}" "${RUNTIME_DIR}/bing_accounts.json" "b64"
    elif [ -n "${BING_ACCOUNTS_JSON:-}" ]; then
      decode_secret_to_file "${BING_ACCOUNTS_JSON}" "${RUNTIME_DIR}/bing_accounts.json" "plain"
    else
      echo "missing Bing account secret: BING_ACCOUNTS_JSON_B64 or BING_ACCOUNTS_JSON" | tee -a "${RUN_META}" >&2
      exit 1
    fi
  fi

  if [ -n "${BING_COOKIE_SNAPSHOT_B64:-}" ] || [ -n "${BING_COOKIE_SNAPSHOT:-}" ]; then
    local first_account_user
    first_account_user="$("${PYTHON_BIN}" - <<'PY' "${RUNTIME_DIR}/bing_accounts.json"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
user = ""
if isinstance(data, list) and data:
    user = (data[0].get("username") or "").strip()
print(user)
PY
)"
    if [ -n "${first_account_user}" ]; then
      local cookie_dir
      cookie_dir="${RUNTIME_DIR}/user_data_${first_account_user%@*}"
      if [ ! -s "${cookie_dir}/browser_cookies.txt" ]; then
        if [ -n "${BING_COOKIE_SNAPSHOT_B64:-}" ]; then
          decode_secret_to_file "${BING_COOKIE_SNAPSHOT_B64}" "${cookie_dir}/browser_cookies.txt" "b64"
        else
          decode_secret_to_file "${BING_COOKIE_SNAPSHOT}" "${cookie_dir}/browser_cookies.txt" "plain"
        fi
      fi
    fi
  fi
}

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

seed_runtime_from_secrets

export TZ="${TZ:-Asia/Shanghai}"
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export BING_SKIP_DEVICE_SECURITY="${BING_SKIP_DEVICE_SECURITY:-1}"
export BING_DATA_DIR="${RUNTIME_DIR}"
export BING_DEBUG_DIR="${DEBUG_DIR}"
export GITHUB_ACTIONS_BING=1
export BING_GITHUB_ARTIFACT_DIR="${RUN_DIR}"

echo "[bing-action] start ${TIMESTAMP}" | tee -a "${RUN_META}"
echo "[bing-action] script=${SCRIPT_PATH}" | tee -a "${RUN_META}"
echo "[bing-action] data_dir=${BING_DATA_DIR}" | tee -a "${RUN_META}"

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

exit "${exit_code}"
