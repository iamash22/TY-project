from __future__ import annotations

import os
from typing import Any, Optional

import httpx


class SupabaseRest:
    def __init__(self) -> None:
        self.url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.anon_key = os.getenv("SUPABASE_ANON_KEY") or ""
        if not self.url or not self.anon_key:
            missing = []
            if not self.url:
                missing.append("SUPABASE_URL")
            if not self.anon_key:
                missing.append("SUPABASE_ANON_KEY")
            raise RuntimeError(
                "Missing required backend environment variables: "
                + ", ".join(missing)
                + ". Add them to backend/.env and restart uvicorn."
            )

    def _headers(self, jwt_token: str | None) -> dict[str, str]:
        # If no user JWT is provided, fall back to anon role by using the anon key as bearer.
        bearer = jwt_token or self.anon_key
        return {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }

    async def insert(self, jwt_token: str | None, table: str, row: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.url}/rest/v1/{table}",
                headers={**self._headers(jwt_token), "Prefer": "return=representation"},
                json=row,
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if isinstance(data, list) and data else data

    async def select(
        self,
        jwt_token: str | None,
        table: str,
        select: str = "*",
        *,
        filters: Optional[dict[str, str]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": select}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.url}/rest/v1/{table}",
                headers=self._headers(jwt_token),
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []

    async def update(
        self,
        jwt_token: str | None,
        table: str,
        patch: dict[str, Any],
        *,
        filters: dict[str, str],
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.patch(
                f"{self.url}/rest/v1/{table}",
                headers={**self._headers(jwt_token), "Prefer": "return=representation"},
                params={**filters},
                json=patch,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []

