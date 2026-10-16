@echo off
rem Dev UI server — port 5173. `%~dp0` keeps it path-independent.
cd /d "%~dp0"
npm run dev -- --port 5173 --strictPort false