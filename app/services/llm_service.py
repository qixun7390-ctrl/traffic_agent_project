import logging
from typing import Any, Sequence
from app.core.config import settings

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)
class LLMConfigurationError(RuntimeError):
    """LLM配置不完整"""

class LLMResponseError(RuntimeError):
    """LLM 返回了无法使用的响应"""



class LLMService:
    """统一管理Traffic Agent与大模型之间的通信"""

    def __init__(self) -> None:
        if not settings.LLM_API_KEY:
            raise LLMConfigurationError(
                "没有配置 LLM_API_KEY"
            )

        self.model = settings.LLM_MODEL

        self.chat_model = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )

    async def generate_message(
        self,
        messages: list[BaseMessage]
    ) -> BaseMessage:
        """
        返回完整的BaseMessage
        """
        return await self.chat_model.ainvoke(messages)

    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        history_context: str | None = None,
    ) -> str:
        """调用大模型并返回文本结果"""
        messages = [
            SystemMessage(content=system_prompt),
        ]
        if history_context:
            messages.append(SystemMessage(content=history_context))
        messages.append(HumanMessage(content=user_message))
        response = await self.chat_model.ainvoke(messages)

        content = response.content

        if isinstance(content,str):
            text = content.strip()
        elif isinstance(content,list):
            text = self._extract_text_blocks(
                content
            )
        else:
            text = str(content).strip()
        if not text:
            raise LLMResponseError(
                "LLM返回内容为空"
            )
        return text

    @staticmethod
    def _extract_text_blocks(
        content: list[Any]
    ) -> str:
        text_parts: list[str] = []
        for block in content:
            if isinstance(block,str):
                text_parts.append(block)
                continue
            if not isinstance(block,dict):
                continue
            text = block.get("text")
            if isinstance(text,str):
                text_parts.append(text)
        return "".join(text_parts).strip()

    def bind_tools(
        self,
        tools: Sequence[BaseTool]
    ) -> Runnable:
        """返回绑定工具后的模型"""
        return self.chat_model.bind_tools(list(tools))