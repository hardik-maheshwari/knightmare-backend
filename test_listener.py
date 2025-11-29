import asyncio
import json
from typing import Dict
import httpx
import websockets
import redis.asyncio as redis

# --- Configuration ---
BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"
REDIS_URL = "redis://localhost:6379"

# Creds
KYOYA = {"username": "kyoya", "password": "leone123"} # White
RYUGA = {"username": "ryuga", "password": "ldrago456"} # Black

# --- API Helpers ---
async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]) -> str:
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    resp.raise_for_status()
    return resp.json()["data"]["token"]

async def make_move(client: httpx.AsyncClient, game_id: str, token: str, move_uci: str, player_name: str):
    print(f"♟️  {player_name} plays: {move_uci}")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"{BASE_URL}/api/games/{game_id}/moves/",
        headers=headers,
        json={"move": move_uci},
    )
    resp.raise_for_status()

async def request_takeback(client: httpx.AsyncClient, game_id: str, token: str):
    print(f"🙏 Kyoya (White) REQUESTS a takeback...")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(f"{BASE_URL}/api/games/{game_id}/takeback/request/", headers=headers)
    resp.raise_for_status()

async def respond_takeback(client: httpx.AsyncClient, game_id: str, token: str, accepted: bool):
    decision = "ACCEPTS" if accepted else "DECLINES"
    print(f"👍 Ryuga (Black) {decision} the takeback.")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"{BASE_URL}/api/games/{game_id}/takeback/respond/", 
        headers=headers,
        json={"accepted": accepted}
    )
    resp.raise_for_status()

# --- Main Test ---
async def main():
    print("\n======== 🧪 STARTING HANDSHAKE UNDO TEST (CHECKMATE REVERSAL) 🧪 ========\n")

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. SETUP
        print("--- 🛠️  Setting up Users & Game ---")
        await client.post(f"{BASE_URL}/api/auth/register/", json=KYOYA)
        await client.post(f"{BASE_URL}/api/auth/register/", json=RYUGA)
        t_white = await get_token(client, KYOYA)
        t_black = await get_token(client, RYUGA)

        # Create & Join
        resp = await client.post(f"{BASE_URL}/api/games/", headers={"Authorization": f"Bearer {t_white}"})
        game_id = resp.json()["data"]["game_id"]
        await client.post(f"{BASE_URL}/api/games/{game_id}/join/", headers={"Authorization": f"Bearer {t_black}"})
        print(f"✅ Game {game_id} Created & Active.\n")

        # 2. LISTENER SETUP
        # We use asyncio Events to synchronize the test script with WebSocket events
        offer_received_event = asyncio.ensure_future(asyncio.Future())
        undo_complete_event = asyncio.ensure_future(asyncio.Future())
        
        async def websocket_listener():
            # Get Ticket for Black
            resp = await client.post(f"{BASE_URL}/api/games/{game_id}/ws-ticket/", headers={"Authorization": f"Bearer {t_black}"})
            ticket = resp.json()["data"]["ticket"]
            
            async with websockets.connect(f"{WS_BASE_URL}/api/games/{game_id}/ws?ticket={ticket}") as ws:
                print("🎧 Listener (Ryuga) Connected.")
                while True:
                    msg = await ws.recv()
                    payload = json.loads(msg)
                    msg_type = payload.get("type")
                    data = payload.get("data", {})

                    if msg_type == "takeback_offered":
                        print(f"✨ WS EVENT: Takeback Offered by {data['requester_username']}")
                        if not offer_received_event.done():
                            offer_received_event.set_result(True)

                    elif msg_type == "game_update":
                        last_move = data.get("last_move")
                        status = data.get("status")
                        print(f"📡 WS EVENT: Game Update | Status: {status} | Last Move: {last_move}")
                        
                        # Detect the Reversal:
                        # We expect status to go BACK to 'active' and last_move to go BACK to 'g8f6'
                        if status == "active" and last_move == "g8f6" and not undo_complete_event.done():
                            print("✅ VERIFIED: Game status reverted to ACTIVE. Undo successful.")
                            undo_complete_event.set_result(True)

        listener_task = asyncio.create_task(websocket_listener())
        await asyncio.sleep(1)

        try:
            # 3. PLAY SCHOLAR'S MATE
            print("--- ⚔️  Executing Scholar's Mate ---")
            moves = [
                (t_white, "e2e4", "White"),
                (t_black, "e7e5", "Black"),
                (t_white, "d1h5", "White"),
                (t_black, "b8c6", "Black"),
                (t_white, "f1c4", "White"),
                (t_black, "g8f6", "Black"),
            ]
            for token, move, name in moves:
                await make_move(client, game_id, token, move, name)
                await asyncio.sleep(0.2)

            # THE CHECKMATE MOVE
            await make_move(client, game_id, t_white, "h5f7", "White") 
            print("💀 CHECKMATE delivered. Game is now in WHITE_WIN state.")
            await asyncio.sleep(1)

            # 4. REQUEST TAKEBACK
            print("\n--- 🤝 Starting Handshake Protocol ---")
            await request_takeback(client, game_id, t_white)
            
            # Wait for WS event
            await asyncio.wait_for(offer_received_event, timeout=5)
            print("✅ Verification: Offer received via WebSocket.")

            # 5. ACCEPT TAKEBACK
            await respond_takeback(client, game_id, t_black, accepted=True)

            # Wait for Board Reversion
            await asyncio.wait_for(undo_complete_event, timeout=5)

            # 6. RESUME PLAY
            print("\n--- ▶️  Resuming Game ---")
            # White plays the checkmate again to finish up
            await make_move(client, game_id, t_white, "h5f7", "White")
            print("💀 CHECKMATE delivered (again).")

        except Exception as e:
            print(f"\n❌ TEST FAILED: {e}")
            listener_task.cancel()
            exit(1)

        print("\n🎉🎉 FULL TEST PASSED: Checkmate undone, Status restored, Game finished. 🎉🎉")
        listener_task.cancel()

if __name__ == "__main__":
    # Flush Redis
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True) # type: ignore
        asyncio.run(r.flushdb()) # type: ignore
    except: pass
    asyncio.run(main())