# Facilities Manager Business App

This folder contains the business version of the facilities management system.

## Start

Double-click `start-facilities-manager.bat`, or run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\server.ps1
```

Then open:

```text
http://127.0.0.1:8088
```

Default first-run login:

```text
Username: admin
Password: ChangeMe123!
```

To set a different first-run admin before the database is created:

```powershell
$env:FM_ADMIN_USER="admin"
$env:FM_ADMIN_PASSWORD="your-strong-password"
python server.py
```

## What Changed From The Prototype

- Data is stored in `data/state.json`, not only inside the browser.
- The app has a login screen.
- The same system can be shared from one host computer.
- Server backups can be downloaded from the dashboard.
- Your existing export/import buttons still work.

## Sharing On Your Network

By default the app only listens on this computer. To let other devices on the same trusted network connect, start it like this:

```powershell
$env:FM_HOST="0.0.0.0"
powershell -NoProfile -ExecutionPolicy Bypass -File .\server.ps1
```

Other devices can then use the host computer's network address with port `8088`.

## Daily Operating Routine

1. Keep `server.py` running during the work day.
2. Add staff in Ops Team first.
3. Assign work orders, maintenance, and housekeeping items to team members.
4. Use Planning and Dashboard Analytics each morning.
5. Download a Server Backup daily or weekly.

## Files

- `server.ps1`: Windows business server.
- `server.py`: optional Python/SQLite business server for machines with Python installed.
- `facilities-manager.html`: the app interface.
- `data/state.json`: created automatically when the app saves data.
- `start-facilities-manager.bat`: Windows start shortcut.
