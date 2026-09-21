#!/usr/bin/env bash
# Idempotent setup for the planes compute listener.
# Does not print COMPUTE_TOKEN. Does not record a host address in the repo.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash infra/bootstrap-vps.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

REPO_URL="${PLANES_REPO_URL:-https://github.com/anabol21/planes.git}"
BRANCH="${PLANES_BRANCH:-runtime/MIS-001-vps-loop}"
APP_DIR=/opt/planes
ENV_DIR=/etc/planes
ENV_FILE="${ENV_DIR}/planes-compute.env"
PLACEHOLDER_TOKEN="replace-with-a-long-random-token"

apt-get update
apt-get install -y python3-venv git curl

if ! id -u planes >/dev/null 2>&1; then
  useradd --system --user-group --create-home --home-dir /var/lib/planes --shell /usr/sbin/nologin planes
fi

install -d -m 755 /var/log/planes
chown planes:planes /var/log/planes

if [[ -d "${APP_DIR}" && ! -d "${APP_DIR}/.git" ]]; then
  if [[ -z "$(ls -A "${APP_DIR}")" ]]; then
    rmdir "${APP_DIR}"
  else
    echo "Refusing to replace non-git directory ${APP_DIR}" >&2
    exit 1
  fi
fi

if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
fi

git -C "${APP_DIR}" fetch origin "${BRANCH}"
git -C "${APP_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"

if [[ ! -x "${APP_DIR}/venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/venv"
fi

chown -R planes:planes "${APP_DIR}" /var/log/planes

install -d -m 755 "${ENV_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  install -m 600 -o planes -g planes "${APP_DIR}/infra/planes-compute.env.example" "${ENV_FILE}"
fi
chown planes:planes "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

install -m 644 "${APP_DIR}/infra/planes-compute.service" /etc/systemd/system/planes-compute.service
systemctl daemon-reload
systemctl enable planes-compute.service

token_value="$(python3 - "${ENV_FILE}" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
value = ""
for line in text.splitlines():
    if line.startswith("COMPUTE_TOKEN="):
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
print(value)
PY
)"

if [[ -z "${token_value}" || "${token_value}" == "${PLACEHOLDER_TOKEN}" ]]; then
  echo "planes-compute.service is enabled but not started. Set COMPUTE_TOKEN in ${ENV_FILE}, then: systemctl restart planes-compute.service" >&2
  exit 0
fi

systemctl restart planes-compute.service
echo "planes-compute.service restarted."
