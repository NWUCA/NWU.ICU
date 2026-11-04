#!/usr/bin/env bash
# Source only an operator-owned env file. Never print its contents.
config_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_file="${ENV_FILE:-${config_root}/.env.production}"
if [[ ! -f "$config_file" && -z "${ENV_FILE:-}" ]]; then
  config_file="${config_root}/.env.production.example"
fi
[[ -f "$config_file" ]] || { echo "Configuration file not found: $config_file" >&2; return 1; }
set -a
# Defaults apply to deployment shell variables; container env_file must be up to date.
source "${config_root}/.env.production.example"
# shellcheck disable=SC1090
source "$config_file"
set +a
# ENV_FILE inside an env template can be relative. Always retain the selected file.
export ENV_FILE="$(realpath "$config_file")"
