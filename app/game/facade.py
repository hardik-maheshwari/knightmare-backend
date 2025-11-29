# import asyncio
from typing import Dict, Any, Optional

import chess
from app.auth.models import User
from app.common.utils import generate_game_id
from app.game.commands.request_takeback import RequestTakebackCommand
from app.game.commands.respond_takeback import RespondTakebackCommand
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
from app.managers.game_manager import GameWebSocketManager
from app.logger_setup import get_logger
from app.game.commands.make_move import MakeMoveCommand

logger = get_logger(__name__)


class GameFacade:
    def __init__(
        self,
        game_repo: GameRepository,
        auth_repo: AuthRepository,
        ws_manager: GameWebSocketManager,
    ):
        self.game_repo = game_repo
        self.auth_repo = auth_repo
        self.ws_manager = ws_manager

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

        # 5. Assemble the final, clean payload.
        payload: Dict[str, Any] = {
            "type": "game_update",
            "data": {
                "game_id": game_id,
                # --- FIX: Directly use the prepared data dictionaries ---
                "white_player": white_player_data,
                "black_player": black_player_data,
                # --- End Fix ---
                "status": game.status.value,
                "current_fen": current_fen,
                "turn": "w" if board.turn == chess.WHITE else "b",
                "is_check": board.is_check(),
                "is_checkmate": board.is_checkmate(),
                "is_draw": board.is_stalemate()
                or board.is_insufficient_material()
                or board.is_seventyfive_moves()
                or board.is_fivefold_repetition(),
                "moves": [move.move_notation for move in moves],
            },
        }

        return payload

    async def join_game(self, game_id: str, joining_player: User) -> Game:
        game = await self.game_repo.get_game_with_players(game_id)

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
        Orchestrates a takeback.
        """
        logger.debug(
            f"--- Requesting Undo for game '{game_id}' by '{user.username}' ---"
        )

        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
            raise GameNotFoundError(f"Game {game_id} not found")

        # Authorization Rule:
        # For Beta: Only allow if user is a player.
        # (In real app, you'd check if opponent agreed, etc.)
        if user.user_id not in (game.white_player_id, game.black_player_id):
            # Or raise UserNotPlayerError
            logger.warning("User tried to undo but is not a player.")
            return

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


    async def respond_takeback(self, game_id: str, user: User, is_accepted: bool) -> None:
        """
        Orchestrates the response (handshake end).
        """
        game = await self.game_repo.get_game_with_players(game_id, for_update=True)
        if not game:
            raise GameNotFoundError(f"Game {game_id} not found")
            
        if user.user_id not in (game.white_player_id, game.black_player_id):
             raise UserNotPlayerError("Only players can respond to takebacks.")

        command = RespondTakebackCommand(game, user, is_accepted, self.game_repo, self.ws_manager)
        await command.execute()
