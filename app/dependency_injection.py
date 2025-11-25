from quart import current_app
from sqlalchemy.ext.asyncio import AsyncSession
from typing import cast

from app.auth.repository import AuthRepository
from app.auth.auth_facade import AuthFacade
from app.auth.websocket_auth_facade import WebSocketAuthFacade
from app.game.repository import GameRepository
from app.game.facade import GameFacade
from app.managers.game_manager import GameWebSocketManager
from app.extensions import redis_client
from quart_bcrypt import Bcrypt


class Container:
    """
    A simple Dependency Injection Container.
    Centralizes the creation of Facades and Services.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

        # Repositories (Cached per container instance)
        self._game_repo = None
        self._auth_repo = None

    @property
    def game_repo(self) -> GameRepository:
        if not self._game_repo:
            self._game_repo = GameRepository(self.session)
        return self._game_repo

    @property
    def auth_repo(self) -> AuthRepository:
        if not self._auth_repo:
            self._auth_repo = AuthRepository(self.session)
        return self._auth_repo

    @property
    def ws_manager(self) -> GameWebSocketManager:
        # Fetched from global app context
        return cast(GameWebSocketManager, current_app.ws_manager)  # type: ignore

    def get_game_facade(self) -> GameFacade:
        return GameFacade(
            game_repo=self.game_repo,
            auth_repo=self.auth_repo,
            ws_manager=self.ws_manager,
        )

    def get_auth_facade(self) -> AuthFacade:
        secret_key = current_app.config["SECRET_KEY"]  # type: ignore

        return AuthFacade(
            auth_repo=self.auth_repo,
            bcrypt=Bcrypt(current_app),
            secret_key=secret_key,  # type: ignore
        )

    def get_ws_auth_facade(self) -> WebSocketAuthFacade:
        return WebSocketAuthFacade(
            auth_repo=self.auth_repo,
            game_repo=self.game_repo,
            redis_client=redis_client,
        )


def get_container(session: AsyncSession) -> Container:
    return Container(session)
