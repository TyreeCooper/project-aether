# Deploy Project Aether on Azure

Two public HTTPS apps in one resource group. No local server.

1. Create resource group `aether-rg`, ACR `aetheracr`, Container Apps Environment `aether-env`.
2. `az acr build -r aetheracr -t aether-api:paper ./backend`
3. Create `aether-api` Container App, ingress external, port 8000, `AETHER_ENV=paper`.
4. Copy API URL. Rebuild web:
   `az acr build -r aetheracr -t aether-web:paper --build-arg NEXT_PUBLIC_API_BASE=https://API-FQDN ./frontend`
5. Create `aether-web` Container App, ingress external, port 3000.
6. Set API env `FRONTEND_ORIGIN` to the web URL.

Open the web URL on your phone.
