# Cloud deploy (no local workstation required)

Project Aether does **not** require Azure. It needs any host that can run:

1. A public HTTPS URL for the Next.js UI
2. A public HTTPS URL for the FastAPI API

The UI links to the API with one variable:

```
NEXT_PUBLIC_API_BASE=https://YOUR-API-HOST
```

Set `FRONTEND_ORIGIN` on the API to the UI URL so the browser is allowed to call it.
