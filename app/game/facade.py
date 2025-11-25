# import asyncio
from typing import Dict, Any, Optional, Tuple, cast

import chess
from app.auth.models import User
from app.common.utils import generate_game_id
from app.game.exceptions import (
    AlreadyInGameError,
    GameNotFoundError,
    GameNotJoinableError,
)
from app.game.models import Game, GameStatus, Move, PlayerColor
from app.game.repository import GameRepository
from app.auth.repository import AuthRepository
from app.managers.game_manager import GameWebSocketManager
from app.logger_setup import get_logger

from app.game.rules.context import MoveContext
from app.game.rules.handlers import (
    GameActiveRule,
    PlayerAuthRule,
    TurnRule,
    LegalMoveRule,
)

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

    async def _load_board_from_history(
        self, game_id: str
    ) -> Tuple[chess.Board, Optional[Move]]:
        """Loads the chess.Board object from the latest move in the DB."""
        latest_move = await self.game_repo.get_latest_move(game_id)
        current_fen = (
            latest_move.board_fen_after_move if latest_move else chess.STARTING_FEN
        )
        logger.debug(f"Loading board with FEN: {current_fen}")
        return chess.Board(current_fen), latest_move

    def _get_captured_piece_symbol(
        self, board: chess.Board, move: chess.Move
    ) -> Optional[str]:
        """Determines if a move is a capture and returns the captured piece's symbol."""
        if board.is_capture(move):
            if board.is_en_passant(move):
                return "p" if board.turn == chess.WHITE else "P"

            captured_piece = board.piece_at(move.to_square)
            if captured_piece:
                return captured_piece.symbol()
        return None

    def _update_game_status(self, game: Game, board: chess.Board) -> None:
        """Checks for game-ending conditions and updates the game status."""
        if board.is_checkmate():
            game.status = (
                GameStatus.WHITE_WIN
                if board.turn == chess.BLACK
                else GameStatus.BLACK_WIN
            )
            logger.info(
                f"Checkmate detected. Game {game.game_id} status set to {game.status.value}"
            )
        elif (
            board.is_stalemate()
            or board.is_insufficient_material()
            or board.is_seventyfive_moves()
            or board.is_fivefold_repetition()
        ):
            game.status = GameStatus.DRAW
            logger.info(
                f"Draw detected. Game {game.game_id} status set to {game.status.value}"
            )

    def _create_new_move(
        self,
        game: Game,
        board: chess.Board,
        move_object: chess.Move,
        latest_move: Optional[Move],
        player: User,
        captured_piece_symbol: Optional[str],
    ) -> Move:
        """
        Creates and returns a new Move domain object based on the game state.
        This method does NOT save the object.
        """
        player_color = (
            PlayerColor.WHITE
            if player.user_id == game.white_player_id
            else PlayerColor.BLACK
        )

        if latest_move is None:
            new_move_number = 1
        elif latest_move.player_color == PlayerColor.BLACK:
            new_move_number = latest_move.move_number + 1
        else:
            new_move_number = latest_move.move_number

        new_fen = board.fen()
        # Data integrity check for a potential bug in the chess library's FEN generation on checkmate
        if board.is_checkmate() and ("k" not in new_fen or "K" not in new_fen):
            logger.warning(
                f"Invalid FEN '{new_fen}' on checkmate. Reverting FEN to pre-move state."
            )
            # Temporarily undo the move to get the last valid FEN
            board.pop()
            new_fen = board.fen()
            # Re-apply the move to keep the board state consistent for subsequent checks
            board.push(move_object)

        new_move = Move(
            game_id=game.game_id,
            move_number=new_move_number,
            player_color=player_color,
            move_notation=move_object.uci(),
            board_fen_after_move=new_fen,
            is_check=board.is_check(),
            is_checkmate=board.is_checkmate(),
            is_castling=board.is_castling(move_object),
            captured_piece=captured_piece_symbol,
        )

        logger.debug(f"Created new unsaved Move object: {new_move.move_notation}")
        return new_move

    def _build_websocket_payload(self, game: Game, latest_move: Move) -> Dict[str, Any]:
        """
        Lightweight serializer for broadcasts.
        O(1) Complexity. Uses game.current_fen and avoids fetching history.
        """
        # We use the stored FEN to create the board object instantly
        board = chess.Board(game.current_fen)

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

        return {
            "type": "game_update",
            "data": {
                "game_id": game.game_id,
                "white_player": white_player_data,
                "black_player": black_player_data,
                "status": game.status.value,
                "current_fen": game.current_fen,  # Use the column!
                "turn": "w" if board.turn == chess.WHITE else "b",
                "is_check": board.is_check(),
                "is_checkmate": board.is_checkmate(),
                "is_draw": board.is_stalemate() or board.is_insufficient_material(),
                # OPTIMIZATION: We only send the latest move, not the whole list.
                # The frontend should append this to its local list.
                "last_move": latest_move.move_notation,
                "moves": [],  # We send empty list or remove it to signal "no history sent"
            },
        }

    async def make_move(self, game_id: str, player: User, move_uci: str) -> Move:
        """
        Orchestrates the entire process of making a move using Chain of Responsibility
        for validation.
        """
        logger.debug(
            f"--- make_move orchestrator started for game '{game_id}' by user '{player.username}' ---"
        )

        # 1. Fetch Data (Repositories)

        game = await self.game_repo.get_game_with_players(game_id,for_update=True)
        if not game:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")

        board, latest_move = await self._load_board_from_history(game_id)
        
        # logger.warning("--- SABOTAGE: Pausing to allow race condition ---")
        # await asyncio.sleep(0.5)

        # 2. Create Context
        # Package all necessary data into our Context Object
        move_context = MoveContext(
            game=game,
            player=player,
            move_uci=move_uci,
            board=board,
            latest_move_db=latest_move,
        )

        # 3. Build & Execute Validation Chain
        # We link the rules in specific order:
        # Active? -> Authorized? -> Turn? -> Legal?
        validation_chain = GameActiveRule()
        validation_chain.set_next(PlayerAuthRule()).set_next(TurnRule()).set_next(
            LegalMoveRule()
        )

        # This will RAISE an exception if any rule fails.
        # It will also ENRICH the context (ctx.parsed_move) if it succeeds.
        validation_chain.check(move_context)

        # 4. Retrieve Enriched Data
        # We trust LegalMoveRule to have populated this
        move_object = cast(chess.Move, move_context.parsed_move)

        # 5. Execute Side Effects (State Mutation)
        captured_piece_symbol = self._get_captured_piece_symbol(board, move_object)

        board.push(move_object)  # Update board state
        self._update_game_status(game, board)  # Check for checkmate/draw
        game.current_fen = board.fen()

        # 6. Persist
        new_move = self._create_new_move(
            game=game,
            board=board,
            move_object=move_object,
            latest_move=latest_move,
            player=player,
            captured_piece_symbol=captured_piece_symbol,
        )

        await self.game_repo.save_move(new_move)

        # 7. Broadcast
        ws_payload = self._build_websocket_payload(game, new_move)

        await self.ws_manager.publish_event(game_id, ws_payload)

        logger.info(f"Move '{move_uci}' successfully processed for game '{game_id}'.")
        return new_move
