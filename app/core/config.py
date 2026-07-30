from pydantic_settings import BaseSettings,SettingsConfigDict
from pathlib import Path

#通过BaseSettings，自动读取.env文件中的变量，并进行类型校验
class Settings(BaseSettings):
    """应用程序设置"""
    # 基本应用设置
    PROJECT_NAME: str = "Traffic Agent"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # API设置
    API_V1_STR: str = "/api/v1"

    # 数据库设置
    DATABASE_URL: str = ""
    DATABASE_HOST: str = ""
    DATABASE_PORT: int = ""
    DATABASE_NAME: str = ""
    DATABASE_USER: str = ""
    DATABASE_PASSWORD: str = ""
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    #LangGraph checkpoint 设置
    LANGGRAPH_CHECKPOINT_DATABASE_URL: str = ""

    # JWT安全设置
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # LLM 配置
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: float = 30.0
    temperature: float = 0.0
    max_tokens: int = 1000

    # 远端仿真平台配置
    SIMULATION_PLATFORM_BASE_URL: str = ""
    SIMULATION_PLATFORM_TOKEN: str = ""

    # 存储位置
    SIMULATION_ARTIFACT_ROOT: str = "D:/PythonProject2/traffic_agent_project_backend/storage"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
settings = Settings()