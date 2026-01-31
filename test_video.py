import asyncio
import json
from typing import Dict, Any
import httpx
import websockets
import redis.asyncio as redis

# --- Configuration ---
BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"
REDIS_URL = "redis://localhost:6379"

# Creds
KYOYA = {"username": "kyoya", "password": "leone123"} 
RYUGA = {"username": "ryuga", "password": "ldrago456"} 

# --- API Helpers ---
async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]) -> str:
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    resp.raise_for_status()
    return resp.json()["data"]["token"]

async def send_signal(client: httpx.AsyncClient, game_id: str, token: str, signal_type: str, payload: Any):
    print(f"📡 Sending Signal: {signal_type} -> {payload}")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"{BASE_URL}/api/games/{game_id}/signal/",
        headers=headers,
        json={"type": signal_type, "payload": payload},
    )
    resp.raise_for_status()

# --- Main Test ---
async def main():
    print("\n======== 🎥 VIDEO SIGNALING INTEGRATION TEST 🎥 ========\n")

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. SETUP USERS & GAME
        print("--- 🏗️  Setting up Users & Game ---")
        await client.post(f"{BASE_URL}/api/auth/register/", json=KYOYA)
        await client.post(f"{BASE_URL}/api/auth/register/", json=RYUGA)
        t_kyoya = await get_token(client, KYOYA)
        t_ryuga = await get_token(client, RYUGA)

        # Create & Join
        resp = await client.post(f"{BASE_URL}/api/games/", headers={"Authorization": f"Bearer {t_kyoya}"})
        game_id = resp.json()["data"]["game_id"]
        await client.post(f"{BASE_URL}/api/games/{game_id}/join/", headers={"Authorization": f"Bearer {t_ryuga}"})
        print(f"✅ Game {game_id} Created & Active.\n")

        # 2. LISTENER SETUP (Ryuga listens)
        signal_received_event = asyncio.ensure_future(asyncio.Future())
        
        async def websocket_listener():
            # Get Ticket for Ryuga
            resp = await client.post(f"{BASE_URL}/api/games/{game_id}/ws-ticket/", headers={"Authorization": f"Bearer {t_ryuga}"})
            ticket = resp.json()["data"]["ticket"]
            
            async with websockets.connect(f"{WS_BASE_URL}/api/games/{game_id}/ws?ticket={ticket}") as ws:
                print("🎧 Listener (Ryuga) Connected via WS.")
                while True:
                    msg = await ws.recv()
                    payload = json.loads(msg)
                    msg_type = payload.get("type")
                    data = payload.get("data", {})

                    if msg_type == "signal_update":
                        print(f"✨ WS EVENT: Signal Received! Type: {data['signal_type']} | Payload: {data['payload']}")
                        # Check if it matches what we expect
                        if data['signal_type'] == "video_peer_id" and data['payload'] == "test-peer-id-123":
                            signal_received_event.set_result(True)
                            return # Exit listener on success

        listener_task = asyncio.create_task(websocket_listener())
        await asyncio.sleep(1) # Wait for WS connection

        try:
            # 3. SEND SIGNAL (Kyoya sends his Video ID)
            print("--- 📡 Kyoya broadcasting Video ID ---")
            await send_signal(client, game_id, t_kyoya, "video_peer_id", "test-peer-id-123")

            # 4. WAIT FOR VERIFICATION
            await asyncio.wait_for(signal_received_event, timeout=5)
            print("✅ VERIFIED: Ryuga received the Peer ID via WebSocket.")

        except Exception as e:
            print(f"\n❌ TEST FAILED: {e}")
            listener_task.cancel()
            exit(1)

        print("\n🎉 SIGNALING TEST PASSED 🎉")
        listener_task.cancel()

if __name__ == "__main__":
    # Flush Redis
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True) # type: ignore
        asyncio.run(r.flushdb()) # type: ignore
    except: pass
    asyncio.run(main())