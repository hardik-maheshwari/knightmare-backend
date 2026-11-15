# import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import chess
from app.auth.models import User
from app.common.utils import generate_game_id
from app.game.commands.claim_timeout import ClaimTimeoutCommand
from app.game.commands.request_takeback import RequestTakebackCommand
from app.game.commands.resign_game import ResignGameCommand
from app.game.commands.respond_takeback import RespondTakebackCommand
from app.game.commands.send_chat import SendChatCommand
from app.game.commands.undo_move import UndoLastMoveCommand
from app.game.exceptions import (
    AlreadyInGameError,
    GameNotFoundError,
    GameNotJoinableError,
    UserNotPlayerError,
)
from app.game.models import Game, GameStatus, PlayerColor
from app.game.repository import GameRepository
from app.auth.repository import AuthRepository
from app.managers.publisher import EventPublisher
from app.logger_setup import get_logger
from app.game.commands.make_move import MakeMoveCommand

logger = get_logger(__name__)


class GameFacade:
    def __init__(
        self,
        game_repo: GameRepository,
        auth_repo: AuthRepository,
        ws_manager: EventPublisher,
    ):
        self.game_repo = game_repo
        self.auth_repo = auth_repo
        self.ws_manager = ws_manager

    async def _get_game_for_player(self, game_id: str, user: User) -> Game:
        """Fetch a game, ensuring it exists and that `user` is one of its players."""
        game = await self.game_repo.get_game_by_id(game_id)
        if game is None:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")
        if user.user_id not in (game.white_player_id, game.black_player_id):
            raise UserNotPlayerError("You are not a player in this game.")
        return game

    async def create_game(self, creator: User) -> Game:
        """
        Orchestrates the creation of a new game.
        """
        logger.debug(f"FACADE: Creating a new game for user '{creator.username}'.")

        # 1. Business Logic: Generate a unique ID for the game.
        game_id = generate_game_id()

        # 2. Business Logic: Assign the creator's color.
        assigned_color = PlayerColor.WHITE

        # 3. Business Logic: Prepare the Game object based on rules.
        game_kwargs: Dict[str, Any] = {
            "game_id": game_id,
            "status": GameStatus.WAITING_FOR_OPPONENT,
        }
        if assigned_color == PlayerColor.WHITE:
            game_kwargs["white_player_id"] = creator.user_id
        else:
            game_kwargs["black_player_id"] = creator.user_id

        new_game = Game(**game_kwargs)

        # 4. Delegate Persistence: Tell the repository to save the fully-formed object.
        created_game = await self.game_repo.save_game(new_game)

        logger.info(
            f"FACADE: Successfully orchestrated creation of game '{created_game.game_id}'."
        )

        # 5. Return the persisted object.
        return created_game

    async def get_serialized_game_state(
        self, game_id: str, game_obj: Optional[Game] = None
    ) -> Dict[str, Any]:
        """
        Assembles the rich game state payload for WebSocket broadcasts.
        """
        # 1. Call the efficient repository method to get the game and its players.
        if game_obj:
            game = game_obj
        else:
            # Fallback: fetch if not provided (e.g. when called from other contexts)
            game = await self.game_repo.get_game_with_players(game_id)
            if not game:
                logger.warning(
                    f"Failed to serialize state: Game '{game_id}' not found."
                )
                raise GameNotFoundError(f"Game with ID {game_id} not found.")

        # 2. Fetch the game's moves.
        moves = await self.game_repo.get_moves_for_game(game_id)

        # 3. Calculate board state from the moves.
        # current_fen = (
        #     chess.STARTING_FEN if not moves else moves[-1].board_fen_after_move
        # )
        current_fen = game.current_fen
        board = chess.Board(current_fen)

        # 4. Prepare the player data dictionaries from the eagerly loaded objects.
        white_player_data = None
        if game.white_player:
            white_player_data = {
                "id": game.white_player.user_id,
                "username": game.white_player.username,
            }

        black_player_data = None
        if game.black_player:
            black_player_data = {
                "id": game.black_player.user_id,
                "username": game.black_player.username,
            }

        chat_history_objs = await self.game_repo.get_chat_history(game_id)
        chat_history: List[Dict[str, Any]] = [
            {
                "message_id": msg.message_id,
                "sender_username": msg.sender.username,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
            }
            for msg in chat_history_objs
        ]

        # 5. Assemble the final, clean payload.
        payload: Dict[str, Any] = {
            "type": "game_update",
            "data": {
                "game_id": game_id,
                "white_player": white_player_data,
                "black_player": black_player_data,
                "status": game.status.value,
                "current_fen": current_fen,
                "turn": "w" if board.turn == chess.WHITE else "b",
                "is_check": board.is_check(),
                "is_checkmate": board.is_checkmate(),
                # Status is authoritative: repetition draws need the move
                # history, which a FEN alone doesn't carry.
                "is_draw": game.status == GameStatus.DRAW,
                "moves": [move.move_notation for move in moves],
                "chat_history": chat_history,
                "white_time_ms": game.white_time_ms,
                "black_time_ms": game.black_time_ms,
                "last_move_at": (
                    game.last_move_at.isoformat() if game.last_move_at else None
                ),
            },
        }

        return payload

    async def join_game(self, game_id: str, joining_player: User) -> Game:
        # Row lock: two users joining at once are serialized, and the second one
        # sees status=ACTIVE and gets GameNotJoinableError.
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)

        if game is None:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")

        if game.status != GameStatus.WAITING_FOR_OPPONENT:
            raise GameNotJoinableError("Game cannot be joined")

        white_player_id = game.white_player_id
        black_player_id = game.black_player_id

        if joining_player.user_id in (white_player_id, black_player_id):
            raise AlreadyInGameError("You cannot play against yourself")

        if white_player_id is None:
            game.white_player_id = joining_player.user_id

        else:
            game.black_player_id = joining_player.user_id

        game.status = GameStatus.ACTIVE

        game.white_time_ms = 3 * 60 * 1000
        game.black_time_ms = 3 * 60 * 1000

        game.last_move_at = datetime.now(timezone.utc)

        # 1. Send the UPDATE SQL to the database
        await self.game_repo.session.flush()

        # Since we just flushed an UPDATE, and updated_at is server_default/onupdate,
        # SQLAlchemy marks it as expired. Accessing it requires IO.
        # In Async, implicit IO is banned. We MUST refresh explicitly here.
        await self.game_repo.session.refresh(game)

        logger.info(
            f"User {joining_player.user_id} joined game {game_id}. Game is now ACTIVE."
        )

        rich_event_payload = await self.get_serialized_game_state(
            game_id, game_obj=game
        )

        await self.ws_manager.publish_event(game_id, rich_event_payload)

        return game

    async def make_move(self, game_id: str, player: User, move_uci: str) -> chess.Move:
        """
        Orchestrates the process of making a move by delegating to the MakeMoveCommand.
        """
        logger.debug(
            f"--- make_move (Command Pattern) started for game '{game_id}' by user '{player.username}' ---"
        )

        # 1. Fetch Data (Repositories)
        # We still need to fetch the game here to pass it into the Command.
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)

        if not game:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")

        # 2. Instantiate the Command
        command = MakeMoveCommand(
            game=game,
            player=player,
            move_uci=move_uci,
            game_repo=self.game_repo,
            ws_manager=self.ws_manager,
        )

        # 3. Execute the Command
        # This runs validation, mutation, persistence, and broadcast.
        move_result = await command.execute()

        logger.info(
            f"Command executed successfully. Move {move_result.move_id} created."
        )
        return move_result

    async def undo_last_move(self, game_id: str, user: User) -> None:
        """
        God-mode undo: takes back the last move without the opponent's consent.
        """
        logger.debug(
            f"--- Requesting Undo for game '{game_id}' by '{user.username}' ---"
        )

        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
            raise GameNotFoundError(f"Game {game_id} not found")

        # "God mode" (testing only): a player undoes without the opponent's
        # approval. The route is disabled unless ENABLE_GOD_MODE_UNDO is set;
        # normal play goes through the request/respond takeback handshake.
        if user.user_id not in (game.white_player_id, game.black_player_id):
            raise UserNotPlayerError("Only players can undo moves.")

        command = UndoLastMoveCommand(game, self.game_repo, self.ws_manager)
        await command.execute()

    async def request_takeback(self, game_id: str, user: User) -> None:
        """
        Orchestrates the request (handshake start).
        """
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
            raise GameNotFoundError(f"Game {game_id} not found")

        # Validate user is a player
        if user.user_id not in (game.white_player_id, game.black_player_id):
            raise UserNotPlayerError("Only players can request takebacks.")

        command = RequestTakebackCommand(game, user, self.game_repo, self.ws_manager)
        await command.execute()

    async def respond_takeback(
        self, game_id: str, user: User, is_accepted: bool
    ) -> None:
        """
        Orchestrates the response (handshake end).
        """
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
            raise GameNotFoundError(f"Game {game_id} not found")

        if user.user_id not in (game.white_player_id, game.black_player_id):
            raise UserNotPlayerError("Only players can respond to takebacks.")

        command = RespondTakebackCommand(
            game, user, is_accepted, self.game_repo, self.ws_manager
        )
        await command.execute()

    async def broadcast_signal(
        self, game_id: str, sender: User, signal_type: str, payload: Any
    ) -> None:
        """
        Pass-through method for WebRTC signaling (PeerIDs, Ice Candidates).
        Does not persist to DB.

        Only the game's players may signal: otherwise anyone could inject their
        own peer ID and receive both players' camera/mic streams.
        """
        await self._get_game_for_player(game_id, sender)
        message: Dict[str, Any] = {
            "type": "signal_update",
            "data": {
                "sender_id": sender.user_id,
                "sender_username": sender.username,
                "signal_type": signal_type,
                "payload": payload,
            },
        }
        await self.ws_manager.publish_event(game_id, message)

    async def send_chat_message(self, game_id: str, sender: User, content: str) -> None:
        await self._get_game_for_player(game_id, sender)
        command = SendChatCommand(
            game_id, sender, content, self.game_repo, self.ws_manager
        )
        await command.execute()

    async def resign_game(self, game_id: str, user: User) -> None:
        """
        Orchestrates a resignation.
        """
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
            raise GameNotFoundError(f"Game {game_id} not found")

        command = ResignGameCommand(game, user, self.game_repo, self.ws_manager)
        await command.execute()
        
    async def claim_timeout(self, game_id: str) -> None:
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
             raise GameNotFoundError(f"Game {game_id} not found")
        
        command = ClaimTimeoutCommand(game, self.game_repo, self.ws_manager)
        await command.execute()