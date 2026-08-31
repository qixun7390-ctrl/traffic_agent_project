import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fileinput import close
from app.agent.agent import init_agent_runtime, close_agent_runtime
from fastapi import FastAPI
from app.api.v1.api import api_router
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db,close_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时执行的操作"""

    #启动时初始化数据库
    await init_db()
    await init_agent_runtime()

    yield
    
    await close_agent_runtime()
    await close_db()

app = FastAPI(
    title="Traffic Agent Project Backend",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router,prefix="/api/v1")

@app.get("/")
def root():
    return {"message":"Traffic Agent backend is running"}
