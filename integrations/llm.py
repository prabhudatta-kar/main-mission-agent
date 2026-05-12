import logging

from openai import AsyncOpenAI, RateLimitError, AuthenticationError
from fastapi import HTTPException

from config.settings import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self._client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def complete(self, messages: list, model: str = None, max_tokens: int = 500) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=model or OPENAI_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except RateLimitError as e:
            logger.error(f"OpenAI quota/rate limit: {e}")
            raise HTTPException(status_code=429, detail="OpenAI quota exceeded — add credits at platform.openai.com/settings/billing")
        except AuthenticationError as e:
            logger.error(f"OpenAI auth error: {e}")
            raise HTTPException(status_code=401, detail="OpenAI API key is invalid")
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            raise HTTPException(status_code=502, detail=f"LLM error: {str(e)}")

    async def complete_with_image(self, system: str, text: str,
                                   image_b64: str, mime_type: str = "image/jpeg",
                                   max_tokens: int = 400) -> str:
        """GPT-4o vision call — passes image as base64 alongside a text prompt."""
        try:
            response = await self._client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}",
                            "detail": "low",
                        }},
                        {"type": "text", "text": text},
                    ]},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except RateLimitError as e:
            logger.error(f"OpenAI vision quota/rate limit: {e}")
            raise HTTPException(status_code=429, detail="OpenAI quota exceeded")
        except Exception as e:
            logger.error(f"OpenAI vision error: {e}")
            raise


llm = LLMClient()
