"""PostgreSQL persistence for Project Aether.

Azure production uses the App Service system-assigned managed identity created by
Service Connector. Local development can opt in with DATABASE_URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from typing import Any

import asyncpg
from azure.identity import DefaultAzureCredential

from app.pnl import summarize_fills

POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
