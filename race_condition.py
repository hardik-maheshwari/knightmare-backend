import asyncio
from typing import Dict
import httpx

BASE_URL = "http://localhost:8080"

# We need two users to make the game ACTIVE
USER_A = {"username": "racer_white", "password": "password123"}
USER_B = {"username": "racer_black", "password": "password123"}


async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]):
    # Register (ignore error if exists)
    await client.post(f"{BASE_URL}/api/auth/register/", json=creds)
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    return resp.json()["data"]["token"]


async def send_move(
    client: httpx.AsyncClient, game_id: str, token: str, move: str, move_name: str
):
    print(f"🚀 Firing request for {move_name} ({move})...")
    try:
        resp = await client.post(
            f"{BASE_URL}/api/games/{game_id}/moves/",
            headers={"Authorization": f"Bearer {token}"},
            json={"move": move},
        )
        print(f"🏁 Response for {move_name}: {resp.status_code}")
        return resp.status_code
    except Exception as e:
        print(f"❌ Error {move_name}: {e}")
        return 500


async def main():
    async with httpx.AsyncClient(timeout=10) as client:
        print("--- Setting up Users ---")
        token_a = await get_token(client, USER_A)
        token_b = await get_token(client, USER_B)

        # 1. User A creates Game
        headers_a = {"Authorization": f"Bearer {token_a}"}
        game_resp = await client.post(f"{BASE_URL}/api/games/", headers=headers_a)
        game_id = game_resp.json()["data"]["game_id"]
        print(f"--- Game Created: {game_id} (Status: Waiting) ---")

        # 2. User B Joins Game (CRITICAL STEP)
        # This flips status from WAITING_FOR_OPPONENT -> ACTIVE
        headers_b = {"Authorization": f"Bearer {token_b}"}
        await client.post(f"{BASE_URL}/api/games/{game_id}/join/", headers=headers_b)
        print(f"--- User B joined. Game is now ACTIVE. ---")

        # 3. THE EXPLOIT: User A fires two moves instantly
        print("\n--- Attempting Race Condition (Simultaneous Moves) ---")

        # Both moves are valid openings for White
        task1 = send_move(client, game_id, token_a, "e2e4", "Move A (e4)")
        task2 = send_move(client, game_id, token_a, "d2d4", "Move B (d4)")

        # Wait for both
        results = await asyncio.gather(task1, task2)

        print("\n--- RESULTS ---")
        if results == [201, 201]: # type: ignore
            print("❌ CRITICAL FAILURE: Both moves were accepted!")
            print("The DB has corrupt history (Two 'Move #1' entries).")
        elif 201 in results and (409 in results or 500 in results):
            print("✅ SUCCESS: Logic held up. One move accepted, one rejected.")
        else:
            print(f"⚠️  Unexpected: {results}")


if __name__ == "__main__":
    asyncio.run(main())
