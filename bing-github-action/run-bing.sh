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
PROXY_DIR="${RUNTIME_DIR}/proxy"
MIHOMO_BIN="${PROXY_DIR}/mihomo"
MIHOMO_CONFIG="${PROXY_DIR}/config.yaml"
MIHOMO_LOG="${RUN_DIR}/mihomo.log"
MIHOMO_PID=""

mkdir -p "${RUN_DIR}" "${RUNTIME_DIR}" "${DEBUG_DIR}" "${PROXY_DIR}"

{
  echo "timestamp=${TIMESTAMP}"
  echo "runner_host=$(hostname)"
  echo "runner_user=$(whoami)"
  echo "script_path=${SCRIPT_PATH}"
  echo "python_bin=${PYTHON_BIN}"
  echo "runtime_dir=${RUNTIME_DIR}"
  echo "debug_dir=${DEBUG_DIR}"
} > "${RUN_META}"

if [ ! -e "${SCRIPT_PATH}" ]; then
  echo "missing required path: ${SCRIPT_PATH}" | tee -a "${RUN_META}" >&2
  exit 1
fi

if [[ "${PYTHON_BIN}" == */* ]]; then
  if [ ! -x "${PYTHON_BIN}" ]; then
    echo "missing required python executable: ${PYTHON_BIN}" | tee -a "${RUN_META}" >&2
    exit 1
  fi
elif ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "missing required python executable in PATH: ${PYTHON_BIN}" | tee -a "${RUN_META}" >&2
  exit 1
fi

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

  if [ -n "${BING_APP_REFRESH_TOKEN_B64:-}" ] || [ -n "${BING_APP_REFRESH_TOKEN:-}" ]; then
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
      local token_dir
      token_dir="${RUNTIME_DIR}/user_data_${first_account_user%@*}"
      if [ ! -s "${token_dir}/app_token.txt" ]; then
        if [ -n "${BING_APP_REFRESH_TOKEN_B64:-}" ]; then
          decode_secret_to_file "${BING_APP_REFRESH_TOKEN_B64}" "${token_dir}/app_token.txt" "b64"
        else
          decode_secret_to_file "${BING_APP_REFRESH_TOKEN}" "${token_dir}/app_token.txt" "plain"
        fi
      fi
    fi
  fi
}

before_debug="$(mktemp)"
after_debug="$(mktemp)"
cleanup() {
  if [ -n "${MIHOMO_PID}" ]; then
    kill "${MIHOMO_PID}" >/dev/null 2>&1 || true
    wait "${MIHOMO_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "${before_debug}" "${after_debug}"
}
trap cleanup EXIT

install_mihomo() {
  if [ -x "${MIHOMO_BIN}" ]; then
    return 0
  fi

  local api_json tag asset_name asset_url archive
  api_json="$("${PYTHON_BIN}" - <<'PY'
import json
import urllib.request

url = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
with urllib.request.urlopen(url, timeout=30) as resp:
    data = json.loads(resp.read().decode("utf-8"))

tag = data.get("tag_name", "")
preferred = [
    f"mihomo-linux-amd64-compatible-{tag}.gz",
    f"mihomo-linux-amd64-{tag}.gz",
]
assets = data.get("assets", [])
chosen = None
for name in preferred:
    for item in assets:
        if item.get("name") == name:
            chosen = item
            break
    if chosen:
        break

if not chosen:
    for item in assets:
        name = item.get("name", "")
        if name.startswith("mihomo-linux-amd64") and name.endswith(".gz") and "go" not in name:
            chosen = item
            break

if not chosen:
    raise SystemExit("no linux amd64 mihomo asset found")

print(tag)
print(chosen["name"])
print(chosen["browser_download_url"])
PY
)"
  tag="$(printf '%s\n' "${api_json}" | sed -n '1p')"
  asset_name="$(printf '%s\n' "${api_json}" | sed -n '2p')"
  asset_url="$(printf '%s\n' "${api_json}" | sed -n '3p')"

  echo "[bing-action] installing mihomo ${tag} (${asset_name})" | tee -a "${RUN_META}"
  archive="$(mktemp)"
  curl -fsSL "${asset_url}" -o "${archive}"
  gzip -dc "${archive}" > "${MIHOMO_BIN}"
  rm -f "${archive}"
  chmod +x "${MIHOMO_BIN}"
}

start_proxy_if_configured() {
  if [ -z "${BING_PROXY_CONFIG_B64:-}" ] && [ -z "${BING_PROXY_CONFIG:-}" ]; then
    echo "[bing-action] proxy not configured" | tee -a "${RUN_META}"
    return 0
  fi

  if [ -n "${BING_PROXY_CONFIG_B64:-}" ]; then
    decode_secret_to_file "${BING_PROXY_CONFIG_B64}" "${MIHOMO_CONFIG}" "b64"
  else
    decode_secret_to_file "${BING_PROXY_CONFIG}" "${MIHOMO_CONFIG}" "plain"
  fi

  install_mihomo

  echo "[bing-action] starting mihomo proxy" | tee -a "${RUN_META}"
  "${MIHOMO_BIN}" -d "${PROXY_DIR}" -f "${MIHOMO_CONFIG}" > "${MIHOMO_LOG}" 2>&1 &
  MIHOMO_PID="$!"

  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:9090/proxies >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "${MIHOMO_PID}" >/dev/null 2>&1; then
      echo "[bing-action] mihomo exited unexpectedly" | tee -a "${RUN_META}" >&2
      tail -n 100 "${MIHOMO_LOG}" >&2 || true
      exit 1
    fi
    sleep 1
  done

  if ! curl -fsS --max-time 2 http://127.0.0.1:9090/proxies >/dev/null 2>&1; then
    echo "[bing-action] mihomo controller not ready" | tee -a "${RUN_META}" >&2
    tail -n 100 "${MIHOMO_LOG}" >&2 || true
    exit 1
  fi

  export HTTP_PROXY="${BING_HTTP_PROXY:-http://127.0.0.1:7890}"
  export HTTPS_PROXY="${BING_HTTPS_PROXY:-http://127.0.0.1:7890}"
  export ALL_PROXY="${BING_ALL_PROXY:-socks5://127.0.0.1:7891}"
  export http_proxy="${HTTP_PROXY}"
  export https_proxy="${HTTPS_PROXY}"
  export all_proxy="${ALL_PROXY}"
  export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
  export no_proxy="${NO_PROXY}"
  export BING_BROWSER_PROXY_SERVER="${BING_BROWSER_PROXY_SERVER:-socks5://127.0.0.1:7891}"
  export BING_SEARCH_HOME_URL="${BING_SEARCH_HOME_URL:-https://www.bing.com/?form=ML2PCO}"
  export BING_SEARCH_REQUEST_URL="${BING_SEARCH_REQUEST_URL:-https://www.bing.com/search}"

  echo "[bing-action] proxy enabled: HTTP_PROXY=${HTTP_PROXY}, BING_BROWSER_PROXY_SERVER=${BING_BROWSER_PROXY_SERVER}" | tee -a "${RUN_META}"
  echo "[bing-action] proxy public ip:" | tee -a "${RUN_META}"
  curl -fsSL --max-time 20 https://api.ipify.org | tee -a "${RUN_META}" || true
  echo | tee -a "${RUN_META}"
  curl -fsSL --max-time 20 https://ipinfo.io/json | tee -a "${RUN_META}" || true
  echo | tee -a "${RUN_META}"
}

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

start_proxy_if_configured

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
