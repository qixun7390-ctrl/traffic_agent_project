from typing import AsyncGenerator
from sqlalchemy import text
from app.core.config import settings
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine,AsyncSession
from sqlalchemy.ext.declarative import declarative_base
import logging

logger = logging.getLogger(__name__)

#创建异步引擎
engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://","postgresql+asyncpg://"),
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    #echo=settings.DEBUG
    echo=True,  # 打印 SQL，帮助调试
    pool_pre_ping=True,  # 连接前检查有效性
)

#创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

#创建ORM模型的基类
Base = declarative_base()

def get_async_engine():
    """
    获取异步数据库引擎
    """
    return engine

async def get_db() -> AsyncGenerator[AsyncSession,None]:
    """
    获取数据库会话的依赖项
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db() -> None:
    """
    初始化数据库并创建表
    """
    try:
        async with engine.begin() as conn:
            if "postgresql" in settings.DATABASE_URL:
                try:
                    await conn.execute(
                        text("CREATE EXTENSION IF NOT EXISTS vector")
                    )
                    logger.info("pgvector扩展已启用")
                except Exception as e:
                    logger.warning(f"无法使用pgvector扩展:{e}")

            #初始化 - 建表
            await conn.run_sync(Base.metadata.create_all)

        logger.info(f"数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败:{e}")
        raise

async def close_db() -> None:
    """
    关闭数据库连接
    """
    try:
        await engine.dispose()
        logger.info("数据库已关闭")
    except Exception as e:
        logger.error(f"关闭数据库失败:{e}")

async def check_db_connection() -> None:
    """
    检查数据库连接
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            return True

    except Exception as e:
        logger.error(f"数据库连接检查失败:{e}")
        return False