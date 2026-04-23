import time
import openai
from app.providers.base import BaseProvider
from app.schemas.messages import CanonicalMessage, MessageMetadata
from app.schemas.providers import ProviderResponse


class OpenAIProvider(BaseProvider):
    name = "openai"
    default_model = "gpt-4o"
    cheapest_model = "gpt-4o-mini"

    async def send_prompt(
        self,
        messages: list[CanonicalMessage],
        api_key: str,
        model: str | None = None,
    ) -> ProviderResponse:
        client = openai.AsyncOpenAI(api_key=api_key)
        target_model = model or self.default_model
        provider_messages = self.to_provider_messages(messages)

        start = time.monotonic()
        try:
            response = await client.chat.completions.create(
                model=target_model,
                messages=provider_messages,
                max_tokens=4096,
            )
        except openai.APIError as e:
            return ProviderResponse(
                message=CanonicalMessage(role="assistant", content=""),
                error=str(e),
            )
        latency_ms = int((time.monotonic() - start) * 1000)

        content = response.choices[0].message.content or ""
        tokens_used = (response.usage.prompt_tokens + response.usage.completion_tokens) if response.usage else None

        return ProviderResponse(
            message=CanonicalMessage(
                role="assistant",
                content=content,
                metadata=MessageMetadata(
                    provider="openai",
                    model=target_model,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                ),
            )
        )

    async def validate_key(self, api_key: str) -> tuple[bool, str | None]:
        client = openai.AsyncOpenAI(api_key=api_key)
        try:
            await client.chat.completions.create(
                model=self.cheapest_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True, None
        except openai.AuthenticationError as e:
            return False, str(e)
        except openai.APIError as e:
            return False, str(e)
