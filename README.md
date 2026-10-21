# LingChat / A2D Studio

Auto CP, Story maker, and ASMR.

This fork is developing A2D Studio as a project-centered script editor and playback tool on top of LingChat.

## Run A2D Studio on Windows

1. Double-click [`start-a2d-studio.bat`](./start-a2d-studio.bat). It starts the frontend, backend, GSV1, and GSV2, then opens `http://127.0.0.1:5173/studio`.
2. Each run writes the launcher and service logs under `tmp/a2d-runs/<run-id>/`.
3. Double-click [`stop-a2d-studio.bat`](./stop-a2d-studio.bat) to stop the processes started by that run.

The launcher expects the Python environment at `.venv`, installed frontend dependencies under `frontend_vue/node_modules`, and GPT-SoVITS at `../third_party/GPT-SoVITS-v2pro-20250604`. Keep local API keys and service settings in `.env`; do not include that file in commits or project exports.

See the [A2D Studio development plan](./docs/develop/a2d-studio-development-plan.md) for current priorities, verified status, and remaining boundaries.
