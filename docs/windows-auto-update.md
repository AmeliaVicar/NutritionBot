# Windows auto-update

This project includes a Windows scheduled-task deploy path.

What it does:

- checks `origin/main` on a timer
- skips update if the working tree has local uncommitted changes
- applies updates with `git pull --ff-only`
- installs `requirements.txt` when the commit changes
- restarts the bot process managed by the script
- writes logs to `logs/auto-update.log`, `logs/bot.out.log`, and `logs/bot.err.log`

Install once on the server:

```powershell
powershell -ExecutionPolicy Bypass -File C:\NutritionBot\scripts\windows\install-auto-update-task.ps1 -RepoDir C:\NutritionBot
```

If the server uses a specific Python executable, pass it explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File C:\NutritionBot\scripts\windows\install-auto-update-task.ps1 -RepoDir C:\NutritionBot -PythonExe C:\Path\To\python.exe
```

After installing, close the old manual Git Bash bot process once. The scheduled task will start and manage the bot automatically on its next run.

Run one update manually:

```powershell
powershell -ExecutionPolicy Bypass -File C:\NutritionBot\scripts\windows\auto-update.ps1 -RepoDir C:\NutritionBot -RestartBot
```

Remove the scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File C:\NutritionBot\scripts\windows\uninstall-auto-update-task.ps1
```

Notes:

- Keep `src/config.py`, `src/state.json`, `.env`, and `service_account.json` local on the server. They are ignored by git.
- If the server has local code changes, auto-update will log the problem and skip instead of overwriting them.
- The task starts under the Windows user that installed it. For always-on operation, that user should stay logged in, or the bot should be moved to a real Windows service later.
