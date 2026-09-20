# Project Aether

Paper-first Bitcoin (BTC/USD) operator console.

**Live host:** Azure App Service `aether-prod-api` in resource group `aether-rg`.
Push to `main` deploys via `.github/workflows/main_aether-prod-api.yml`.

- UI: `https://aether-prod-api.azurewebsites.net/`
- Health: `/api/v1/health`
- Docs: `/docs`

One site. FastAPI serves the phone page at `/` and the JSON API under `/api/v1`. Live exchange execution is blocked.

Paper ledger is written to disk (`/home/aether/paper_state.json` on App Service) so a restart does not reset the blotter.
