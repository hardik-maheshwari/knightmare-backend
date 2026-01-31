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
KYOYA = {"username": "kyoya", "password": "leone123"} 
RYUGA = {"username": "ryuga", "password": "ldrago456"} 

# --- API Helpers ---
async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]) -> str:
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    resp.raise_for_status()
    return resp.json()["data"]["token"]

async def send_chat(client: httpx.AsyncClient, game_id: str, token: str, message: str):
    print(f"💬 Sending Chat: '{message}'")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"{BASE_URL}/api/games/{game_id}/chat/",
        headers=headers,
        json={"content": message},
    )
    resp.raise_for_status()

async def get_game_state(client: httpx.AsyncClient, game_id: str, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(f"{BASE_URL}/api/games/{game_id}/", headers=headers)
    resp.raise_for_status()
    return resp.json()["data"]

# --- Main Test ---
async def main():
    print("\n======== 💬 CHAT FEATURE INTEGRATION TEST 💬 ========\n")

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
        chat_received_event = asyncio.ensure_future(asyncio.Future())
        ws_connected_event = asyncio.ensure_future(asyncio.Future()) # <--- NEW EVENT
        
        async def websocket_listener():
            try:
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

                        # 1. Wait for Initial State to confirm Subscription is Active
                        if msg_type == "game_update":
                             if not ws_connected_event.done():
                                 print("✅ WS Ready: Initial State Received.")
                                 ws_connected_event.set_result(True)

                        # 2. Listen for Chat
                        if msg_type == "chat_message":
                            print(f"✨ WS EVENT: Chat Received! From: {data['sender_username']} | Msg: {data['content']}")
                            if data['content'] == "You're going down, Ryuga!" and data['sender_username'] == "kyoya":
                                chat_received_event.set_result(True)
                                return 
            except Exception as e:
                print(f"🔥 LISTENER CRASHED: {e}")

        listener_task = asyncio.create_task(websocket_listener())
        
        # --- FIX: Wait for WS to be fully ready (Subscribed) ---
        await asyncio.wait_for(ws_connected_event, timeout=5)
        # ------------------------------------------------------

        try:
            # 3. SEND CHAT (Kyoya talks trash)
            print("--- 🗣️  Kyoya sending message ---")
            await send_chat(client, game_id, t_kyoya, "You're going down, Ryuga!")

            # 4. WAIT FOR REAL-TIME DELIVERY
            await asyncio.wait_for(chat_received_event, timeout=5)
            print("✅ VERIFIED: Ryuga received the message via WebSocket.")
            
            print("⏳ Waiting for DB commit (simulating latency)...")
            await asyncio.sleep(0.5) 

            # 5. VERIFY PERSISTENCE (HISTORY)
            print("\n--- 💾 Verifying Database Persistence ---")
            game_state = await get_game_state(client, game_id, t_ryuga)
            
           
            print(f"DEBUG: Full API Response:\n{json.dumps(game_state, indent=2)}")
            
            history = game_state["data"].get("chat_history", [])
            print(f"History fetched: {len(history)} messages.")
            
            if len(history) > 0 and history[-1]['content'] == "You're going down, Ryuga!":
                print("✅ VERIFIED: Message persisted in Game History.")
            else:
                print(f"DEBUG: Full API Response:\n{json.dumps(game_state, indent=2)}")
                raise Exception("Message not found in game history!")

        except Exception as e:
            print(f"\n❌ TEST FAILED: {repr(e)}") # Using repr() shows the error type
            listener_task.cancel()
            exit(1)

        print("\n🎉 CHAT SYSTEM FUNCTIONAL 🎉")
        listener_task.cancel()

if __name__ == "__main__":
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True) # type: ignore
        asyncio.run(r.flushdb()) # type: ignore
    except: pass
    asyncio.run(main())