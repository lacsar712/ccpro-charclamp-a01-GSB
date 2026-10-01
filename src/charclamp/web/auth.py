from __future__ import annotations

from litestar.connection import ASGIConnection
from litestar.middleware.session.server_side import ServerSideSessionBackend, ServerSideSessionConfig
from litestar.security.session_auth import SessionAuth
from sqlalchemy import select

from charclamp.domain.models import User
from charclamp.infra.db import SessionLocal


async def retrieve_user_handler(session: dict, connection: ASGIConnection) -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.id == int(user_id)))
        return result.scalar_one_or_none()


session_auth = SessionAuth[User, ServerSideSessionBackend](
    retrieve_user_handler=retrieve_user_handler,
    session_backend_config=ServerSideSessionConfig(
        session_id_bytes=32,
    ),
    # 注意："/" 不能放进 exclude——它是正则片段，会匹配到所有路径，
    # 导致认证中间件全站旁路、handler 读 request.user 直接 500。
    # 未登录访问受保护页会抛 NotAuthorizedException，由 main.py 统一重定向到 /login。
    exclude=[r"^/login$", r"^/logout$", r"^/static", r"^/schema", r"^/favicon\.ico$"],
)
