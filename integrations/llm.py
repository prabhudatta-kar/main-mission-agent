from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY, OPENAI_MODEL


class LLMClient:
    def __init__(self):
        self._client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def complete(self, messages: list, model: str = None) -> str:
        response = await self._client.chat.completions.create(
            model=model or OPENAI_MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()


llm = LLMClient()
