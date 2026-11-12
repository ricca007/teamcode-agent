# Classroom workbench

React + TypeScript + Vite. One page contains planning, ownership, Agent logs/diffs, actual pytest and interface history.

From the repository root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
.\.venv\Scripts\python.exe scripts/run_mvp.py --port 8765
```

The backend serves `frontend/dist`. For development use `npm run dev` here; check `vite.config.ts` for the proxy target. `?demo=1` is a labelled read-only offline sample, excluded from experiments. Credentials use per-tab session storage; backend checks enforce permissions.

Backend routes and data boundaries are documented in [the interface contract](../docs/interface_contract.md). Coursework reports are maintained outside this source repository.
