# Azure (what is actually running)

Not Container Apps. Production is:

- Resource group: `aether-rg`
- App Service: `aether-prod-api`
- GitHub Action: `.github/workflows/main_aether-prod-api.yml`
- Startup: `bash startup.sh` (honors Azure `PORT`, default 8000)

Optional App Setting: `PAPER_STATE_PATH=/home/aether/paper_state.json`
