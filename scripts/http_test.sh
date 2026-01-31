#!/bin/bash

# Exit on error and fail on pipeline errors
set -e
set -o pipefail

function reset_db_and_cache() {
    echo -e "\n--- Resetting Database and Cache ---"
    # This command clears the currently selected Redis database (perfect for dev)
    if command -v redis-cli &> /dev/null; then
        redis-cli FLUSHDB
    else
        echo "WARNING: redis-cli not found. Skipping cache flush." >&2
    fi
    
    # Replace 'knightmare' with your actual database name from your .env if different
    if command -v psql &> /dev/null; then
        psql -d knightmare -c "TRUNCATE TABLE users, games, moves RESTART IDENTITY CASCADE;"
    else
        echo "WARNING: psql not found. Skipping DB truncate. Please reset manually." >&2
    fi
    echo "--- Reset Complete. Starting Test Run. ---"
}


reset_db_and_cache

# --- Configuration ---
BASE_URL="http://localhost:8080"
KYOYA_USER="kyoya"
KYOYA_PASS="leone123"
RYUGA_USER="ryuga"
RYUGA_PASS="ldrago456"

login_user() {
  local username=$1
  local password=$2
  echo "--- Logging in as $username ---" >&2
  curl -s -X POST "$BASE_URL/api/auth/login/" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$username\", \"password\": \"$password\"}" | jq -r '.data.token'
}

get_user_id_from_token() {
  local token=$1
  curl -s -X GET "$BASE_URL/api/auth/profile/" \
    -H "Authorization: Bearer $token" | jq -r '.data.user_id'
}

make_move() {
  local player_name=$1
  local token=$2
  local move_uci=$3
  echo -e "\n--- $player_name plays: $move_uci ---" >&2
  
  curl --fail -s -X POST "$BASE_URL/api/games/$GAME_ID/moves/" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{\"move\": \"$move_uci\"}" | jq -e '.'
}

# --- Test Execution ---
echo "======== STARTING BACKEND INTEGRATION TEST ========"

# STEP 1 & 2: Register and Login
echo "--- Registering & Logging in Kyoya and Ryuga ---"
curl -s -X POST "$BASE_URL/api/auth/register/" -H "Content-Type: application/json" -d "{\"username\": \"$KYOYA_USER\", \"password\": \"$KYOYA_PASS\"}" > /dev/null
curl -s -X POST "$BASE_URL/api/auth/register/" -H "Content-Type: application/json" -d "{\"username\": \"$RYUGA_USER\", \"password\": \"$RYUGA_PASS\"}" > /dev/null
KYOYA_TOKEN=$(login_user "$KYOYA_USER" "$KYOYA_PASS")
RYUGA_TOKEN=$(login_user "$RYUGA_USER" "$RYUGA_PASS")
KYOYA_ID=$(get_user_id_from_token "$KYOYA_TOKEN")
RYUGA_ID=$(get_user_id_from_token "$RYUGA_TOKEN")
echo "Kyoya (ID: $KYOYA_ID) and Ryuga (ID: $RYUGA_ID) are ready."

# STEP 3: Create and Join Game
echo "--- Kyoya is creating a new game ---"
CREATE_GAME_RESPONSE=$(curl -s -X POST "$BASE_URL/api/games/" -H "Authorization: Bearer $KYOYA_TOKEN")
GAME_ID=$(echo "$CREATE_GAME_RESPONSE" | jq -r '.data.game_id')
echo "Game created with ID: $GAME_ID"
echo "--- Ryuga is joining the game ---"
curl --fail -s -X POST "$BASE_URL/api/games/$GAME_ID/join/" -H "Authorization: Bearer $RYUGA_TOKEN" > /dev/null
echo "Game is now ACTIVE."

# +++ NEW STEP: TEST THE TICKET ENDPOINT +++
echo -e "\n--- Testing WebSocket Ticket Dispenser ---"
# Kyoya (a player) requests a ticket. This should succeed.
KYOYA_TICKET_RESPONSE=$(curl -s -X POST "$BASE_URL/api/games/$GAME_ID/ws-ticket/" -H "Authorization: Bearer $KYOYA_TOKEN")
KYOYA_TICKET=$(echo "$KYOYA_TICKET_RESPONSE" | jq -r '.data.ticket')

if [ -z "$KYOYA_TICKET" ] || [ "$KYOYA_TICKET" == "null" ]; then
    echo "FAILURE: Kyoya, a valid player, could not get a ticket." >&2
    exit 1
else
    echo "SUCCESS: Kyoya received a ticket: $KYOYA_TICKET"
fi

# Ryuga (the other player) requests a ticket. This should also succeed.
RYUGA_TICKET_RESPONSE=$(curl -s -X POST "$BASE_URL/api/games/$GAME_ID/ws-ticket/" -H "Authorization: Bearer $RYUGA_TOKEN")
RYUGA_TICKET=$(echo "$RYUGA_TICKET_RESPONSE" | jq -r '.data.ticket')
if [ -z "$RYUGA_TICKET" ] || [ "$RYUGA_TICKET" == "null" ]; then
    echo "FAILURE: Ryuga, a valid player, could not get a ticket." >&2
    exit 1
else
    echo "SUCCESS: Ryuga received a ticket: $RYUGA_TICKET"
fi


# --- Scholar's Mate (No changes needed here, it tests the HTTP move response) ---
# NOTE: Dynamic player assignment is removed for simplicity, assuming Kyoya is White for this test.
echo -e "\n======== EXECUTING SCHOLAR'S MATE (Kyoya as White) ========"
sleep 1
make_move "Kyoya" "$KYOYA_TOKEN" "e2e4"
sleep 1
make_move "Ryuga" "$RYUGA_TOKEN" "e7e5"
sleep 1
make_move "Kyoya" "$KYOYA_TOKEN" "d1h5"
sleep 1
make_move "Ryuga" "$RYUGA_TOKEN" "b8c6"
sleep 1
make_move "Kyoya" "$KYOYA_TOKEN" "f1c4"
sleep 1
make_move "Ryuga" "$RYUGA_TOKEN" "g8f6"
sleep 1

FINAL_MOVE_RESPONSE=$(make_move "Kyoya" "$KYOYA_TOKEN" "h5f7")
echo "$FINAL_MOVE_RESPONSE"
echo -e "\n--- Verifying final API response ---"
echo "SUCCESS: Final move command was accepted by the server."

echo -e "\n======== HTTP API TEST COMPLETED SUCCESSFULLY ========"

