# Maintaining Services

## Installing and Enabling the Orchestrator

All services and timers here run with user-level permissions (`systemd --user`).

### Prerequisites: User Lingering

By default, `systemd --user` processes terminate when your SSH or terminal session closes. To allow scheduled timers to run headlessly in the background, enable lingering for your account once:

```shell
sudo loginctl enable-linger $USER
```

### Installation

Run the provided installation script from the repository root:

```shell
./scripts/install-systemd.sh
```

The script expects the following files inside the `systemd/` directory:

* `orchestrator@.service` (Template service unit)
* `orchestrator-nightly.timer` (Nightly timer unit)
* `orchestrator-weekly.timer` (Weekly timer unit)
* `service-orchestrator.env-example` (Environment variables template)

The script automatically:

1. Creates target directories (`~/.config/systemd/user` and `~/.config/achterhus`).
2. Copies `service-orchestrator.env-example` to `~/.config/achterhus/service-orchestrator.env` if it does not already exist.
3. Symlinks the template service and timer files to `~/.config/systemd/user/`.
4. Runs `systemd-analyze verify` syntax checks on the unit files.
5. Reloads the user daemon (`systemctl --user daemon-reload`) and enables/starts both timers.

> **Note:** After running the script for the first time, make sure to inspect and update your environment configuration at `~/.config/achterhus/service-orchestrator.env`.

---

## Useful Commands

### Check Active Timers

To verify scheduled execution times for both nightly and weekly runs:

```shell
systemctl --user list-timers 'orchestrator*'
```

### Manual Execution

You can trigger a graph manually at any time without waiting for the timer:

```shell
# Run the nightly graph manually
systemctl --user start orchestrator@nightly.service

# Run the weekly graph manually
systemctl --user start orchestrator@weekly.service
```

### Checking Logs & Status

To view unit status or follow live output across all orchestrator runs:

```shell
# Check status of active timers
systemctl --user status orchestrator-nightly.timer orchestrator-weekly.timer

# Stream logs for all orchestrator service instances
journalctl --user -u 'orchestrator@*' -f
```
