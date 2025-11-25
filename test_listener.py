import asyncio
import json
from typing import Any, Dict
import httpx
import websockets
import redis.asyncio as redis

# --- Configuration ---
BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"
REDIS_URL = "redis://localhost:6379"
KYOYA_CREDS = {"username": "kyoya", "password": "leone123"}
RYUGA_CREDS = {"username": "ryuga", "password": "ldrago456"}


# --- Helper Functions ---
async def get_token(client: httpx.AsyncClient, creds: Dict[str, str]) -> str:
    """Logs in a user and returns their token."""
    resp = await client.post(f"{BASE_URL}/api/auth/login/", json=creds)
    resp.raise_for_status()
    return resp.json()["data"]["token"]


async def make_move(
    client: httpx.AsyncClient, game_id: str, token: str, move_uci: str, player_name: str
):
    """Makes a move via the HTTP API."""
    print(f"--- {player_name} plays: {move_uci} ---")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"{BASE_URL}/api/games/{game_id}/moves/",
        headers=headers,
        json={"move": move_uci},
    )
    resp.raise_for_status()  # Will fail the test if the move is rejected


async def main():
    print("======== STARTING FULL GAME (SCHOLAR'S MATE) LISTENER TEST ========")

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. SETUP: Register users, log them in, create and join a game.
        print("--- Setting up users and game... ---")
        await client.post(f"{BASE_URL}/api/auth/register/", json=KYOYA_CREDS)
        await client.post(f"{BASE_URL}/api/auth/register/", json=RYUGA_CREDS)

        kyoya_token = await get_token(client, KYOYA_CREDS)
        ryuga_token = await get_token(client, RYUGA_CREDS)

        headers_kyoya = {"Authorization": f"Bearer {kyoya_token}"}
        resp = await client.post(f"{BASE_URL}/api/games/", headers=headers_kyoya)
        game_id = resp.json()["data"]["game_id"]
        print(f"Game created with ID: {game_id}")

        headers_ryuga = {"Authorization": f"Bearer {ryuga_token}"}
        await client.post(
            f"{BASE_URL}/api/games/{game_id}/join/", headers=headers_ryuga
        )
        print("Game is now ACTIVE.")

        # 2. LISTENER SETUP: One player (Ryuga) will listen for all game events.
        final_checkmate_event: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        print(f"The type of final_checkmate_event is {final_checkmate_event}")

        async def game_event_listener():
            # Get a ticket for Ryuga to connect
            resp_ticket = await client.post(
                f"{BASE_URL}/api/games/{game_id}/ws-ticket/", headers=headers_ryuga
            )
            ticket = resp_ticket.json()["data"]["ticket"]
            print(f"--- Listener (Ryuga) got ticket and is connecting... ---")

            ws_url = f"{WS_BASE_URL}/api/games/{game_id}/ws?ticket={ticket}"

            try:
                async with websockets.connect(ws_url) as websocket:
                    print("--- Listener connected! Monitoring all game events... ---")

                    while True:
                        message_str = await websocket.recv()
                        payload = json.loads(message_str)
                        game_data = payload.get("data", {})

                        # We are now looking for the final state of the game.
                        if game_data.get("is_checkmate") is True:
                            print(
                                f"\n+++ CHECKMATE EVENT RECEIVED! +++\n{json.dumps(game_data, indent=2)}\n"
                            )
                            final_checkmate_event.set_result(game_data)
                            break  # Our job is done, exit the loop.
                        else:
                            # Log other game states as they come in
                            moves_so_far = game_data.get("moves", [])
                            print(
                                f"--- Listener received game update. Moves: {len(moves_so_far)} ---"
                            )
            except websockets.exceptions.ConnectionClosed as e:
                if not final_checkmate_event.done():
                    final_checkmate_event.set_exception(e)

        # Start the listener in the background
        listener_task = asyncio.create_task(game_event_listener())
        await asyncio.sleep(
            2
        )  # Give it time to connect and receive the first two events

        # 3. ACTION: Play out Scholar's Mate. Kyoya is White.
        print("\n--- Executing Scholar's Mate sequence... ---")
        try:
            await make_move(client, game_id, kyoya_token, "e2e4", "Kyoya (White)")
            await asyncio.sleep(1)
            await make_move(client, game_id, ryuga_token, "e7e5", "Ryuga (Black)")
            await asyncio.sleep(1)
            await make_move(client, game_id, kyoya_token, "d1h5", "Kyoya (White)")
            await asyncio.sleep(1)
            await make_move(client, game_id, ryuga_token, "b8c6", "Ryuga (Black)")
            await asyncio.sleep(1)
            await make_move(client, game_id, kyoya_token, "f1c4", "Kyoya (White)")
            await asyncio.sleep(1)
            await make_move(client, game_id, ryuga_token, "g8f6", "Ryuga (Black)")
            await asyncio.sleep(1)
            await make_move(
                client, game_id, kyoya_token, "h5f7", "Kyoya (White)"
            )  # The checkmating move

        except httpx.HTTPStatusError as e:
            print(f"\n❌ FATAL: A move was rejected by the server: {e.response.text}")
            listener_task.cancel()
            exit(1)

        # 4. VERIFICATION: Wait for the listener to have its future resolved by the checkmate event.
        print("\n--- Waiting for listener to confirm checkmate event... ---")
        try:
            final_data = await asyncio.wait_for(final_checkmate_event, timeout=5)

            assert final_data["status"] == "white_win"
            assert final_data["is_checkmate"] is True
            assert final_data["last_move"] == "h5f7"

            print(
                "\n✅ SUCCESS: WebSocket listener received the correct 'white_win' and 'is_checkmate' flags."
            )

        except asyncio.TimeoutError:
            print(
                "\n❌ FAILURE: Listener did not receive the final checkmate event within the timeout."
            )
            exit(1)
        finally:
            listener_task.cancel()


if __name__ == "__main__":
    # Clean up DB and Redis before starting
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore
        asyncio.run(r.flushdb())  # type: ignore
        print("--- Redis cache flushed. ---")
        # Add DB cleanup here if needed, but the test handles new users each time
    except Exception as e:
        print(f"Could not flush Redis: {e}")

    asyncio.run(main())
