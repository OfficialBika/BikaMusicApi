"""Minimal async client example for the Bika Music API.

Set MUSIC_API_URL (for example, https://api.example.com/v1) and MUSIC_API_KEY
in the consumer process environment. Never place real credentials in source code.
"""
import asyncio
import os

import httpx


class BikaMusicAPI:
    def __init__(self) -> None:
        self.base_url = os.environ["MUSIC_API_URL"].rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": os.environ["MUSIC_API_KEY"]},
            timeout=httpx.Timeout(20.0, connect=5.0),
        )

    async def search(self, query: str, limit: int = 10) -> dict:
        response = await self.client.get("/search", params={"q": query, "limit": limit})
        response.raise_for_status()
        return response.json()

    async def playback(self, track_id: str) -> dict:
        response = await self.client.get(f"/tracks/{track_id}/playback")
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self.client.aclose()


async def main() -> None:
    api = BikaMusicAPI()
    try:
        result = await api.search(os.environ.get("MUSIC_QUERY", "sample"), limit=5)
        for track in result["items"]:
            print(f'{track["id"]} | {track["title"]} — {track["artist"]}')

        if result["items"]:
            playback = await api.playback(result["items"][0]["id"])
            print("Short-lived playback URL:", playback["url"])
            print("Expires in:", playback["expires_in"], "seconds")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
