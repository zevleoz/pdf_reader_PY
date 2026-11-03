# frontend

React + TypeScript + Vite + Tailwind. Built on a dev machine; the output goes to ../static/app/ and is committed. The server has no Node.

    npm ci          # install exactly what package-lock.json lists
    npm run build   # type-check, then build into ../static/app/

Flask serves the app at /app/ (blueprints/app_shell.py).
