import logging
import httpx
from google import genai
from typing import Optional
from app.core.config import settings

logger = logging.getLogger("grain.llm")

# Initialize the Gemini client (async-safe, no configure() needed)
gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

async def call_gemini(prompt: str) -> str:
    """Calls Gemini as a default/fallback provider."""
    try:
        response = await gemini_client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        raise e

async def call_openai_compatible(url: str, api_key: str, model: str, prompt: str) -> str:
    """Helper to call any OpenAI-compatible API using httpx with detailed error logging."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    async with httpx.AsyncClient(timeout=120.0, http2=False) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"API Call failed to {url} with status {response.status_code}. Response: {response.text}")
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTPStatusError calling {url} for model {model}: {e.response.text}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error calling {url} for model {model}: {e}")
            raise e

async def call_llm(prompt: str, task: str = "general") -> str:
    """
    Unified LLM router that routes queries to the most cost-effective and task-appropriate model.
    
    Routing Strategy:
    - If task is 'intent', 'classify', 'relations', or 'entities' AND Groq API key is set:
        Use Groq LLaMA 8B (fast, cheap, accurate for classification).
    - If task is 'understand' or 'general' AND NVIDIA API key is set:
        Try preferred NVIDIA Model (e.g. DeepSeek v4 Flash).
    - Fallback:
        Falls back to Groq LLaMA 70B (llama-3.3-70b-versatile) for high-quality reasoning.
        Falls back to Gemini 2.5 Flash as final API safeguard.
    """
    # 1. Groq (Preferred for lightweight classification/parsing tasks)
    use_groq = task in ("intent", "classify", "relations", "entities") and settings.GROQ_API_KEY
    if use_groq:
        try:
            logger.info(f"Routing task '{task}' to Groq (llama-3.1-8b-instant)...")
            return await call_openai_compatible(
                url="https://api.groq.com/openai/v1/chat/completions",
                api_key=settings.GROQ_API_KEY,
                model="llama-3.1-8b-instant",
                prompt=prompt
            )
        except Exception as e:
            logger.warning(f"Groq task '{task}' failed ({e}). Falling back to Gemini...")

    # 2. NVIDIA Build (Preferred for heavy comprehension tasks)
    use_nvidia = task in ("understand", "general") and settings.NVIDIA_API_KEY
    if use_nvidia:
        try:
            model = settings.NVIDIA_MODEL
            logger.info(f"Routing task '{task}' to NVIDIA Build ({model})...")
            return await call_openai_compatible(
                url="https://integrate.api.nvidia.com/v1/chat/completions",
                api_key=settings.NVIDIA_API_KEY,
                model=model,
                prompt=prompt
            )
        except Exception as e:
            logger.warning(f"Primary NVIDIA model '{model}' failed ({e}). Falling back to Groq...")

    # 3. Groq 70B Fallback (Premium reasoning, extremely fast and reliable fallback)
    if settings.GROQ_API_KEY and task in ("understand", "general"):
        try:
            logger.info(f"Routing task '{task}' to Groq Fallback (llama-3.3-70b-versatile)...")
            return await call_openai_compatible(
                url="https://api.groq.com/openai/v1/chat/completions",
                api_key=settings.GROQ_API_KEY,
                model="llama-3.3-70b-versatile",
                prompt=prompt
            )
        except Exception as e:
            logger.warning(f"Groq fallback failed ({e}). Falling back to direct DeepSeek or Gemini...")

    # 4. Direct DeepSeek API (Alternative direct endpoint if configured)
    use_deepseek = task in ("understand", "general") and settings.DEEPSEEK_API_KEY
    if use_deepseek:
        try:
            logger.info(f"Routing task '{task}' to direct DeepSeek API (deepseek-chat)...")
            return await call_openai_compatible(
                url="https://api.deepseek.com/chat/completions",
                api_key=settings.DEEPSEEK_API_KEY,
                model="deepseek-chat",
                prompt=prompt
            )
        except Exception as e:
            logger.warning(f"Direct DeepSeek task '{task}' failed ({e}). Falling back to Gemini...")

    # 5. Default / Fallback: Gemini
    try:
        logger.info(f"Routing task '{task}' to Gemini (gemini-2.5-flash)...")
        return await call_gemini(prompt)
    except Exception as e:
        # Final desperate fallback to Groq 8b if Gemini is completely down
        if settings.GROQ_API_KEY:
            try:
                logger.warning(f"Gemini failed. Final failover of task '{task}' to Groq 8B...")
                return await call_openai_compatible(
                    url="https://api.groq.com/openai/v1/chat/completions",
                    api_key=settings.GROQ_API_KEY,
                    model="llama-3.1-8b-instant",
                    prompt=prompt
                )
            except Exception as ge:
                logger.error(f"All LLM providers exhausted. Final failure: {ge}")
        raise e
