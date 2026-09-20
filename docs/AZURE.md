# Azure — one website

You only need **one** Azure Web App. The API and the phone screen are the same URL.

1. portal.azure.com → Create → **Web App**
2. Resource group: new `aether-rg`
3. Name: `aether-paper` (must be unique)
4. Publish: **Code**. Runtime: **Python 3.12**. Region: East US. Pricing: **Basic B1** (or Free F1 to try).
5. Create. Then open the app → **Deployment Center** → GitHub → authorize → repo `TyreeCooper/project-aether` → branch `main`.
6. Configuration → Application settings → add `SCM_DO_BUILD_DURING_DEPLOYMENT=true` and `AETHER_ENV=paper`.
7. Configuration → General settings → Startup command:
   `cd backend && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000`

Open `https://aether-paper.azurewebsites.net` on your phone.

That is the whole cloud setup. No registry. No second app. No CORS variable.
