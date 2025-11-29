from typing import List, Optional
from .models import Game, Move
from app.logger_setup import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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

    async def save_game(self, game: Game) -> Game:
        """
        Adds a new game to the session and refreshes it to load DB-generated values.
        """
        logger.debug(f"Adding new game '{game.game_id}' to the session.")
        self.session.add(game)

        logger.debug("Flushing session to save game to the database.")
        await self.session.flush()

        # logger.debug("Refreshing game instance to get DB defaults.")
        # await self.session.refresh(game)

        return game

    async def get_game_with_players(
        self, game_id: str, for_update: bool = False
    ) -> Optional[Game]:
        """
        Fetches a game and eagerly loads its related player objects.
        If for_update=True, locks the row (SELECT ... FOR UPDATE).
        """
        statement = (
            select(Game)
            .where(Game.game_id == game_id)
            .options(joinedload(Game.white_player), joinedload(Game.black_player))
        )

        if for_update:
            logger.debug(f"🔒 Locking game row '{game_id}' for update.")
            statement = statement.with_for_update(of=Game)

        result = await self.session.execute(statement)
        game = result.scalars().first()

        if game:
            logger.debug(f"Found game {game}")
        else:
            logger.debug(f"Game with game id {game_id} not found")

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

    async def save_move(self, move: Move) -> Move:
        """
        Adds a new Move object to the session, flushes to persist it,
        and refreshes to load all database-generated values.
        """
        logger.debug(
            f"Adding new move #{move.move_number} ('{move.move_notation}') to session."
        )
        self.session.add(move)

        logger.debug(f"Flushing session to save move for game '{move.game_id}'.")
        await self.session.flush()

        # logger.debug(f"Refreshing move instance '{move.move_id}' to get DB defaults.")
        # await self.session.refresh(move)

        return move

    async def get_latest_move(self, game_id: str) -> Optional[Move]:
        """A DRY helper to get the most recent move for a game."""
        statement = (
            select(Move)
            .where(Move.game_id == game_id)
            .order_by(Move.move_number.desc(), Move.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def delete_move(self, move: Move) -> None:
        """
        Hard deletes a move record from the database.
        """
        logger.debug(f"Deleting move {move.move_id} ({move.move_notation}) from DB.")
        await self.session.delete(move)
        await self.session.flush()
