"""
v1端点的主API路由
"""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, agent, simulations

api_router = APIRouter()

api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["authentication"],
)

api_router.include_router(
    agent.router,
    prefix="/agent",
    tags=["agent"]
)

api_router.include_router(
    simulations.router,
    prefix="/simulations",
    tags=["simulations"]
)
@api_router.get("/health")
def health_check():
    return {"status":"ok"}

