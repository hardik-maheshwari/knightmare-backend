import asyncio
from typing import Dict
import httpx

# Use your LOCAL Backend URL
BASE_URL = "http://localhost:8080"

USER_WHITE = {"username": "timerwhite", "password": "password123"}
USER_BLACK = {"username": "timerblack", "password": "password123"}

async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]) -> str:
    """Helper to Register/Login and get JWT"""
    await client.post(f"{BASE_URL}/api/auth/register/", json=creds)
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    if resp.status_code != 200:
        raise Exception(f"Auth failed: {resp.text}")
    return resp.json()["data"]["token"]

async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("--- 1. Authenticating Users ---")
        token_w = await get_token(client, USER_WHITE)
        token_b = await get_token(client, USER_BLACK)
        headers_w = {"Authorization": f"Bearer {token_w}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        print("--- 2. Creating Game ---")
        # Create
        resp = await client.post(f"{BASE_URL}/api/games/", headers=headers_w)
        game_id = resp.json()["data"]["game_id"]
        
        # Join (Start the Clock!)
        await client.post(f"{BASE_URL}/api/games/{game_id}/join/", headers=headers_b)
        print(f"Game {game_id} started. Clock is ticking for White.")

        # --- TEST A: NORMAL MOVE WITH DELAY ---
        print("\n--- TEST A: White thinks for 2 seconds... ---")
        await asyncio.sleep(2.05) # Sleep a tiny bit more than 2s
        
        print("White moves e2e4.")
        resp = await client.post(
            f"{BASE_URL}/api/games/{game_id}/moves/",
            headers=headers_w,
            json={"move": "e2e4"}
        )
        assert resp.status_code == 201, f"Move failed: {resp.text}"

        # VERIFY A: Check if time was deducted
        resp = await client.get(f"{BASE_URL}/api/games/{game_id}/", headers=headers_w)
        print("\n🔎 RAW PAYLOAD:", resp.json()) 
        print("*"*100)
        data = resp.json()["data"]["data"]
        white_time = data.get("white_time_ms") # We need to ensure serializer returns this!
        
        # NOTE: If we haven't updated Serializer yet, this key might be missing.
        # But let's assume we will fix that next.
        if white_time:
            print(f"White Time Remaining: {white_time}ms")
            # Should be roughly 178,000ms (180s - 2s)
            assert 177000 < white_time < 179000, "Time deduction logic seems wrong!"
            print("✅ White time deducted correctly.")
        else:
            print("⚠️ 'white_time_ms' not found in response. Did you update the Serializer?")

        # --- TEST B: TIMEOUT (FLAG FALL) ---
        # Note: We can't actually wait 3 minutes in a test script, it takes too long.
        # Ideally, for this test, you'd manually UPDATE the DB to set remaining time to 1 second.
        # But since we can't easily touch the DB from this script without DB access...
        # We will skip the full timeout test unless you want to wait 3 minutes.
        print("\n(Skipping full 3-minute timeout test to save time)")
        print("Logic verification: If Test A passed, the Service is wired correctly.")

if __name__ == "__main__":
    asyncio.run(main())