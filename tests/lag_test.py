import asyncio
import json
import time
from typing import Dict
import httpx
import websockets

BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"

# Use a fresh game ID every time to ensure clean state
USER_A = {"username": "lag_tester_white", "password": "password123"}
USER_B = {"username": "lag_tester_black", "password": "password123"}


async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]):
    # Register (ignore error if exists)
    await client.post(f"{BASE_URL}/api/auth/register/", json=creds)
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    return resp.json()["data"]["token"]


async def main():
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Setup Game
        print("--- Setting up Game ---")
        token_a = await get_token(client, USER_A)
        token_b = await get_token(client, USER_B)

        # Create (User A is White)
        resp = await client.post(
            f"{BASE_URL}/api/games/", headers={"Authorization": f"Bearer {token_a}"}
        )
        game_id = resp.json()["data"]["game_id"]

        # Join (User B is Black)
        await client.post(
            f"{BASE_URL}/api/games/{game_id}/join/",
            headers={"Authorization": f"Bearer {token_b}"},
        )

        # Get WS Ticket for User B (Black will listen)
        resp = await client.post(
            f"{BASE_URL}/api/games/{game_id}/ws-ticket/",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        ticket = resp.json()["data"]["ticket"]

        print("--- 😴 WAITING 6 SECONDS to ensure Server goes IDLE ---")
        # This ensures the 'Before' code would definitely be in the sleep(5) block
        await asyncio.sleep(6)

        print("--- 🚀 STARTING LATENCY TEST ---")

        # Connect User B (Listener)
        ws_url = f"{WS_BASE_URL}/api/games/{game_id}/ws?ticket={ticket}"
        async with websockets.connect(ws_url) as ws:
            # Consume the initial "connection success" message (Current State)
            await ws.recv()

            start_time = time.time()

            # IMMEDIATELY make a move as User A (White) - FIX: White moves first!
            print(f"--- Move Fired by White at T=0.00s ---")

            resp = await client.post(
                f"{BASE_URL}/api/games/{game_id}/moves/",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"move": "e2e4"},
            )

            if resp.status_code != 201:
                print(f"❌ Move Failed: {resp.text}")
                return

            # Wait for the broadcast to reach User B
            print("--- Waiting for WebSocket Broadcast... ---")
            msg = await ws.recv()
            end_time = time.time()

            data = json.loads(msg)
            print(data)
            elapsed = end_time - start_time

            print(f"--- 🏁 Message Received! Latency: {elapsed:.4f} seconds ---")

            if elapsed < 0.5:
                print("✅ RESULT: INSTANT (Event-Driven architecture works)")
            else:
                print("❌ RESULT: LAGGING (Polling architecture detected)")


if __name__ == "__main__":
    asyncio.run(main())
