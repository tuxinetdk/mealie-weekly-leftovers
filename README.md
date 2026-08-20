# Mealie Update Guard

A conservative update guard for a Docker Compose Mealie installation using PostgreSQL.

## Assumptions for this package

- Mealie directory: `/docker_data/mealie`
- `.env` contains an exact pin such as `MEALIE_VERSION=v3.22.0`
- Mealie container name: `mealie`
- PostgreSQL container name: `mealie-postgres`
- Mealie bind data: `/docker_data/mealie/data` -> `/app/data`
- PostgreSQL is intentionally **not** auto-updated by this guard.

## What it does

- Checks the official GitHub `releases/latest` endpoint hourly.
- Ignores draft/prerelease versions.
- Keeps `MEALIE_VERSION` pinned; never changes to `latest`.
- Blocks automatic scheduling on a Mealie major-version change or obvious breaking/manual-upgrade warnings in release notes.
- Sends a Discord message once when a new stable version is scheduled.
- At 00:00 Europe/Copenhagen:
  1. validates current containers and Mealie health;
  2. stops only the Mealie application container;
  3. creates a PostgreSQL custom-format `pg_dump`;
  4. verifies the dump with `pg_restore -l`;
  5. archives `/app/data` and verifies the tar archive;
  6. stores `.env`, `docker-compose.yml`, Docker inspect metadata and SHA256 checksums;
  7. updates only `MEALIE_VERSION`;
  8. pulls only the Mealie Compose service (not PostgreSQL);
  9. starts Mealie and waits for Docker health;
  10. sends Discord success.
- If the update/health check fails, it restores `.env`, `/app/data`, and the PostgreSQL database, starts the old Mealie version, verifies health, blocks that failed release, and sends Discord rollback status.
- Retains successful update backups for 14 days by default.

## Install

Copy this folder to the Docker host and run:

```bash
chmod +x install.sh mealie-update-guard.sh
sudo ./install.sh
```

The installer prompts for the Discord webhook and stores it in `/etc/mealie-update-guard.conf` with mode `0600`.

## Safe first test

```bash
mealie-update-guard dry-run
mealie-update-guard test-discord
mealie-update-guard backup
mealie-update-guard check
mealie-update-guard status
```

`dry-run` changes nothing. `backup` briefly stops only the Mealie app container so the database and `/app/data` are captured without application writes.

## Systemd

```bash
systemctl status mealie-update-check.timer
systemctl status mealie-auto-update.timer
systemctl list-timers --all 'mealie-*'
```

Logs:

```bash
journalctl -u mealie-update-check.service
journalctl -u mealie-auto-update.service
```

Run a release check manually:

```bash
mealie-update-guard check
```

Run a pending update manually:

```bash
mealie-update-guard update
```

No pending version means the update command exits without changing anything.

## Important design choice

The Compose PostgreSQL image (`postgres:17`) is not pulled by the guard. PostgreSQL major upgrades require a separate migration procedure and should remain outside automatic Mealie application updates.