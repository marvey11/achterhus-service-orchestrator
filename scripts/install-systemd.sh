#!/usr/bin/env bash

set -euo pipefail

# Resolve repository paths safely
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SYSTEMD_DIR="$(realpath "${SCRIPT_DIR}/../systemd")"
CONFIG_DIR="${HOME}/.config/achterhus"
USER_SYSTEMD_DIR="${HOME}/.config/systemd/user"

SERVICE_CONFIG="${CONFIG_DIR}/service-orchestrator.env"
EXAMPLE_CONFIG="${SYSTEMD_DIR}/service-orchestrator.env-example"

SERVICE_UNIT="${SYSTEMD_DIR}/orchestrator@.service"
NIGHTLY_TIMER="${SYSTEMD_DIR}/orchestrator-nightly.timer"
WEEKLY_TIMER="${SYSTEMD_DIR}/orchestrator-weekly.timer"

# Verify required source files exist before proceeding
missing_files=0
for file in "${SERVICE_UNIT}" "${NIGHTLY_TIMER}" "${WEEKLY_TIMER}"; do
    if [[ ! -f "${file}" ]]; then
        echo "❌ Error: Required unit file not found: ${file}" >&2
        missing_files=1
    fi
done

if [[ "${missing_files}" -eq 1 ]]; then
    exit 1
fi

echo "🔧 Configuring systemd user units for orchestrator..."

# Ensure target directories exist
mkdir -p "${USER_SYSTEMD_DIR}" "${CONFIG_DIR}"

# --- Configuration Setup ---

if [[ ! -f "${SERVICE_CONFIG}" ]]; then
    if [[ -f "${EXAMPLE_CONFIG}" ]]; then
        cp "${EXAMPLE_CONFIG}" "${SERVICE_CONFIG}"
        chmod 600 "${SERVICE_CONFIG}"
        echo "📝 Created ${SERVICE_CONFIG} from example template."
        echo "⚠️  Please update ${SERVICE_CONFIG} before proceeding."
    else
        echo "⚠️  Warning: Example config template not found at ${EXAMPLE_CONFIG}" >&2
    fi
else
    echo "ℹ️️  Environment file already exists at ${SERVICE_CONFIG}"
fi

# --- Symlink Unit Files ---

ln -sfn "${SERVICE_UNIT}" "${USER_SYSTEMD_DIR}/orchestrator@.service"
ln -sfn "${NIGHTLY_TIMER}" "${USER_SYSTEMD_DIR}/orchestrator-nightly.timer"
ln -sfn "${WEEKLY_TIMER}" "${USER_SYSTEMD_DIR}/orchestrator-weekly.timer"

# --- Verification & Systemd Deployment ---

echo "🔍 Verifying unit file syntax..."
systemd-analyze verify --user "${USER_SYSTEMD_DIR}/orchestrator@.service"
systemd-analyze verify --user "${USER_SYSTEMD_DIR}/orchestrator-nightly.timer"
systemd-analyze verify --user "${USER_SYSTEMD_DIR}/orchestrator-weekly.timer"

systemctl --user daemon-reload
systemctl --user enable --now orchestrator-nightly.timer orchestrator-weekly.timer

echo ""
echo "✅ Installation complete!"
echo "⏰ Active Timers:"
systemctl --user list-timers 'orchestrator*'
echo ""
echo "📡 Monitoring: journalctl --user -u 'orchestrator@*' -f"
