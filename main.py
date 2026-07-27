from fileinput import close

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
    yield
    #关闭数据库连接
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