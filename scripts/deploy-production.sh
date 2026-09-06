#!/usr/bin/env bash
set -Eeuo pipefail

backend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${1:-${backend_root}/.env.production}"
compose_file="${backend_root}/docker-compose.production.yaml"

for command_name in docker grep install realpath; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this deployment script with sudo so it can prepare the persistent directories." >&2
  exit 1
fi

if [[ ! -f "${env_file}" ]]; then
  cp "${backend_root}/.env.production.example" "${env_file}"
  echo "Created ${env_file}. Replace every CHANGE_ME value, then run this script again." >&2
  exit 2
fi

if grep -q 'CHANGE_ME' "${env_file}"; then
  echo "${env_file} still contains CHANGE_ME placeholders." >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${env_file}"
set +a

: "${MEDIA_STORAGE_HOST_PATH:?missing MEDIA_STORAGE_HOST_PATH}"
: "${STATIC_STORAGE_HOST_PATH:?missing STATIC_STORAGE_HOST_PATH}"
: "${RESOURCE_INDEX_HOST_PATH:?missing RESOURCE_INDEX_HOST_PATH}"
: "${RESOURCE_STORAGE_HOST_PATH:?missing RESOURCE_STORAGE_HOST_PATH}"
: "${PROXY_NETWORK_NAME:?missing PROXY_NETWORK_NAME}"

if [[ ! "${PROXY_NETWORK_NAME}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "PROXY_NETWORK_NAME contains unsupported characters." >&2
  exit 2
fi

upload_uid="${UPLOAD_UID:-10001}"
upload_gid="${UPLOAD_GID:-10001}"
install -d -o "${upload_uid}" -g "${upload_gid}" -m 0750 \
  "${MEDIA_STORAGE_HOST_PATH}" \
  "${STATIC_STORAGE_HOST_PATH}" \
  "${RESOURCE_INDEX_HOST_PATH}"

if [[ ! -d "${RESOURCE_STORAGE_HOST_PATH}" ]]; then
  echo "Resource storage does not exist: ${RESOURCE_STORAGE_HOST_PATH}" >&2
  echo "Create/mount the AList Local storage directory and grant UID ${upload_uid} write access." >&2
  exit 2
fi

if ! docker network inspect "${PROXY_NETWORK_NAME}" >/dev/null 2>&1; then
  docker network create "${PROXY_NETWORK_NAME}" >/dev/null
fi

export ENV_FILE="$(realpath --relative-to="${backend_root}" "${env_file}")"
cd "${backend_root}"

docker compose --env-file "${env_file}" -f "${compose_file}" up -d --build --remove-orphans
docker compose --env-file "${env_file}" -f "${compose_file}" exec -T web \
  python manage.py check --deploy --fail-level ERROR
docker compose --env-file "${env_file}" -f "${compose_file}" exec -T resource-worker \
  test -w /resource-storage

docker compose --env-file "${env_file}" -f "${compose_file}" ps
echo "Application containers are ready. Configure/reload OpenResty as described in deploy/openresty.md."
