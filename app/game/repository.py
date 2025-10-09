import chess

# import random
from typing import Any, Dict, List, Optional, Tuple
from app.auth.models import User
from app.auth.repository import AuthRepository
from app.game.exceptions import (
    AlreadyInGameError,
    GameNotFoundError,
    GameNotJoinableError,
    MoveNotPossibleError,
    UserNotPlayerError,
)
from .models import Game, GameStatus, Move, PlayerColor
from app.logger_setup import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.common.utils import generate_game_id

logger = get_logger(__name__)


class GameRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        logger.debug("Game Repository initialized with a new session.")

    async def get_game_by_id(self, game_id: str) -> Optional[Game]:
        logger.debug(f"Querying for game with game id {game_id}")

        statement = select(Game).where(Game.game_id == game_id)

        result = await self.session.execute(statement)
        game = result.scalars().first()

        if game:
            logger.debug(f"Found game {game}")
        else:
            logger.debug(f"Game with game id {game_id} not found")

        return game

    async def create_game(self, creator: User) -> Game:
        """
        Creates a new game record in the database, assigning the creator
        to a random color.
        """
        logger.debug(f"Attempting to create a new game for user '{creator.username}'.")

        # 1. Generate a unique ID for the game.
        game_id = generate_game_id()
        logger.debug(f"Generated new game_id: {game_id}")

        # 2. Randomly assign the creator to White or Black.
        # assigned_color = random.choice([PlayerColor.WHITE, PlayerColor.BLACK])
        assigned_color = PlayerColor.WHITE
        logger.debug(
            f"Assigning user {creator.user_id} to color: {assigned_color.value}"
        )

        # 3. Prepare the arguments for the new Game object.
        game_kwargs: Dict[str, Any] = {
            "game_id": game_id,
            "status": GameStatus.WAITING_FOR_OPPONENT,
        }

        if assigned_color == PlayerColor.WHITE:
            game_kwargs["white_player_id"] = creator.user_id
            game_kwargs["black_player_id"] = None
        else:
            game_kwargs["white_player_id"] = None
            game_kwargs["black_player_id"] = creator.user_id

        # 4. Create the new Game instance.
        new_game = Game(**game_kwargs)
        logger.debug(f"New Game object created: {new_game}")

        # 5. Add, flush, and refresh the object in the session.
        #    - add(): Puts the object in the session's "to be created" list.
        #    - flush(): Sends the INSERT command to the DB to create the row.
        #    - refresh(): Updates our `new_game` object with any DB-generated
        #                 values (like created_at).
        logger.debug("Adding new game to the session...")
        self.session.add(new_game)

        logger.debug("Flushing session to save game to the database...")
        await self.session.flush()

        logger.debug("Refreshing game instance to get DB defaults...")
        await self.session.refresh(new_game)

        logger.info(
            f"Successfully created game {new_game.game_id} for user {creator.user_id}."
        )

        # 6. Return the fully created game object.
        return new_game

    async def join_game(self, game_id: str, joining_player: User) -> Game:
        game = await self.get_game_by_id(game_id)

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

        logger.info(
            f"User {joining_player.user_id} joined game {game_id}. Game is now ACTIVE."
        )

        return game

    async def get_moves_for_game(self, game_id: str) -> List[Move]:
        """
        Retrieves all moves for a specific game, sorted chronologically.
        """
        logger.debug(f"Querying for all moves in game '{game_id}'")
        statement = (
            select(Move)
            .where(Move.game_id == game_id)
            .order_by(Move.move_number.asc(), Move.created_at.asc())
        )

        result = await self.session.execute(statement)
        moves = result.scalars().all()

        logger.debug(f"Found {len(moves)} moves for game '{game_id}'.")
        return list(moves)

    async def make_move(self, game_id: str, player: User, move_uci: str) -> Move:
        """
        Orchestrates the entire process of making a move.
        It calls a series of private helpers to perform validation and state changes.
        """
        logger.debug(
            f"--- make_move orchestrator started for game '{game_id}' by user '{player.username}' ---"
        )

        game = await self._get_and_validate_game_state(game_id, player)

        board, latest_move = await self._load_board_from_history(game_id)

        move_object = self._validate_move_legality(board, move_uci, player, game)

        # 4. Apply the move to the board and update the game's overall status.
        captured_piece_symbol = self._get_captured_piece_symbol(board, move_object)
        board.push(move_object)
        self._update_game_status(game, board)

        # 5. Persist the new move to the database.
        new_move = await self._create_and_save_new_move(
            game=game,
            board=board,
            move_object=move_object,
            latest_move=latest_move,
            player=player,
            captured_piece_symbol=captured_piece_symbol,
        )

        logger.info(f"Move '{move_uci}' successfully processed for game '{game_id}'.")
        return new_move

    # --- Private Helper Methods ---

    async def _get_and_validate_game_state(self, game_id: str, player: User) -> Game:
        """Fetches the game and runs pre-condition checks."""
        game = await self.get_game_by_id(game_id)
        if not game:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")
        if game.status != GameStatus.ACTIVE:
            raise MoveNotPossibleError(
                f"Game is not active. Status: {game.status.value}"
            )
        if player.user_id not in (game.white_player_id, game.black_player_id):
            raise UserNotPlayerError("You are not a player in this game.")
        return game

    async def _load_board_from_history(
        self, game_id: str
    ) -> Tuple[chess.Board, Optional[Move]]:
        """Loads the chess.Board object from the latest move in the DB."""
        latest_move = await self._get_latest_move(game_id)
        current_fen = (
            latest_move.board_fen_after_move if latest_move else chess.STARTING_FEN
        )
        logger.debug(f"Loading board with FEN: {current_fen}")
        return chess.Board(current_fen), latest_move

    def _validate_move_legality(
        self, board: chess.Board, move_uci: str, player: User, game: Game
    ) -> chess.Move:
        """Validates the move against game rules (turn order, legality)."""
        is_whites_turn = board.turn == chess.WHITE
        if (is_whites_turn and player.user_id != game.white_player_id) or (
            not is_whites_turn and player.user_id != game.black_player_id
        ):
            raise MoveNotPossibleError("It is not your turn.")

        try:
            move_object = chess.Move.from_uci(move_uci)

            if move_object not in board.legal_moves:
                raise chess.IllegalMoveError("Move is not in the list of legal moves.")
            return move_object
        except (ValueError, chess.IllegalMoveError) as e:
            logger.warning(f"Illegal move '{move_uci}' attempted. Reason: {e}")
            raise MoveNotPossibleError(f"Illegal move: {move_uci}")

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

    async def _create_and_save_new_move(
        self,
        game: Game,
        board: chess.Board,
        move_object: chess.Move,
        latest_move: Optional[Move],
        player: User,
        captured_piece_symbol: Optional[str],
    ) -> Move:
        """Creates the new Move object and saves it to the database."""
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
        # Data integrity check for the checkmate FEN bug
        if board.is_checkmate() and ("k" not in new_fen or "K" not in new_fen):
            logger.warning(
                f"Invalid FEN '{new_fen}' detected after checkmate. Reverting to FEN from before the final move to maintain data integrity."
            )
            board.pop()  # Undo the move
            new_fen = board.fen()

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

        self.session.add(new_move)
        await self.session.flush()
        await self.session.refresh(new_move)
        logger.info(
            f"New move #{new_move.move_number} ({new_move.move_notation}) saved for game {game.game_id}"
        )
        return new_move

    async def _get_latest_move(self, game_id: str) -> Optional[Move]:
        """A DRY helper to get the most recent move for a game."""
        statement = (
            select(Move)
            .where(Move.game_id == game_id)
            .order_by(Move.move_number.desc(), Move.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_serialized_game_state(self, game_id: str, auth_repo: AuthRepository):
        
        game = await self.get_game_by_id(game_id)
        if not game:
            logger.warning(f"Broadcast failed: Game '{game_id}' not found.")
            return

        moves = await self.get_moves_for_game(game_id)
        current_fen = (
            chess.Board().fen() if not moves else moves[-1].board_fen_after_move
        )
        board = chess.Board(current_fen)

       
        white_player = (
            await auth_repo.get_user_by_id(game.white_player_id)
            if game.white_player_id
            else None
        )
        black_player = (
            await auth_repo.get_user_by_id(game.black_player_id)
            if game.black_player_id
            else None
        )

        payload: Dict[str, Any] = {
            "type": "game_update",
            "data": {
                "game_id": game_id,
                "white_player": (
                    {"id": white_player.user_id, "username": white_player.username}
                    if white_player
                    else None
                ),
                "black_player": (
                    {"id": black_player.user_id, "username": black_player.username}
                    if black_player
                    else None
                ),
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

