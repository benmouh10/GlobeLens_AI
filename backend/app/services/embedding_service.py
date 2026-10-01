"""
GlobeLens AI — EmbeddingService
Generates and stores vector embeddings for articles.
Pipeline Step 2: SCRAPED → EMBEDDED
"""
import json
import hashlib
from typing import List
import structlog
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.repositories.article_repository import ArticleRepository
from app.repositories.embedding_repository import EmbeddingRepository
from app.services.cache_service import cache_service
from app.services.article_classifier import prepare_embedding_text

logger = structlog.get_logger()


class EmbeddingService:
    """
    Produces vector representations of article text using OpenAI/Grok models.
    Stores vectors in PostgreSQL via pgvector for similarity-based clustering.
    """

    def __init__(self) -> None:
        self._model = settings.EMBEDDING_MODEL
        
        # Configure client dynamically
        if settings.EMBEDDING_PROVIDER == "gemini":
            logger.info("Initializing EmbeddingService client with Gemini config")
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self._client = genai
            except ImportError:
                logger.warn("google-generativeai package not installed, client initialization deferred")
                self._client = None
            self._model = "models/text-embedding-004"
        elif settings.EMBEDDING_PROVIDER == "grok":
            logger.info("Initializing EmbeddingService client with Grok (x.AI) config")
            self._client = AsyncOpenAI(
                api_key=settings.GROK_API_KEY,
                base_url="https://api.x.ai/v1"
            )
            # Use Grok standard embedding fallback if model is default OpenAI
            if self._model == "text-embedding-3-small":
                self._model = "grok-beta"
        elif settings.EMBEDDING_PROVIDER == "azure":
            endpoint = settings.AZURE_EMBEDDING_ENDPOINT or ""
            # Strip trailing /v1, /models, or slash
            endpoint = endpoint.rstrip("/")
            if endpoint.endswith("/v1"):
                endpoint = endpoint[:-3]
            if endpoint.endswith("/models"):
                endpoint = endpoint[:-7]
            endpoint = endpoint.rstrip("/")
            
            logger.info("Initializing EmbeddingService client with Azure AI Foundry config", endpoint=endpoint)
            self._client = AsyncOpenAI(
                api_key=settings.AZURE_EMBEDDING_API_KEY,
                base_url=f"{endpoint}/models",
                default_query={"api-version": "2024-05-01-preview"},
                default_headers={"api-key": settings.AZURE_EMBEDDING_API_KEY}
            )
        elif settings.EMBEDDING_PROVIDER == "ollama":
            logger.info("Initializing EmbeddingService client with Ollama config", model=settings.OLLAMA_EMBEDDING_MODEL)
            self._client = AsyncOpenAI(
                api_key="ollama",
                base_url=settings.OLLAMA_BASE_URL,
                timeout=120.0
            )
            self._model = settings.OLLAMA_EMBEDDING_MODEL
        else:
            logger.info("Initializing EmbeddingService client with OpenAI config")
            self._client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY
            )

    async def generate_vector(self, text: str) -> List[float]:
        """
        Call the embedding model API and return a float vector.
        Caches embeddings by content hash to avoid redundant API calls.
        """
        if not text or not text.strip():
            raise ValueError("Input text cannot be empty")

        # Normalize text and compute hash for caching
        text_bytes = text.encode("utf-8")
        cache_key = f"embedding:{hashlib.sha256(text_bytes).hexdigest()}"
        
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                logger.debug("Embedding cache hit", cache_key=cache_key)
                return json.loads(cached)
        except Exception as cache_err:
            logger.warn("Cache lookup failed, proceeding to API call", error=str(cache_err))

        # Check if API keys are placeholders to avoid slow/failing requests during local dev
        is_placeholder = False
        if settings.EMBEDDING_PROVIDER == "azure":
            is_placeholder = not settings.AZURE_EMBEDDING_API_KEY or "your_" in settings.AZURE_EMBEDDING_API_KEY
        elif settings.EMBEDDING_PROVIDER == "grok":
            is_placeholder = not settings.GROK_API_KEY or "your_" in settings.GROK_API_KEY
        elif settings.EMBEDDING_PROVIDER == "gemini":
            is_placeholder = not settings.GEMINI_API_KEY or "your_" in settings.GEMINI_API_KEY
        elif settings.EMBEDDING_PROVIDER == "ollama":
            # Local inference needs no credential, only a reachable daemon.
            is_placeholder = not settings.OLLAMA_BASE_URL
        else:  # openai
            is_placeholder = not settings.OPENAI_API_KEY or "your_" in settings.OPENAI_API_KEY

        if is_placeholder:
            logger.warn("Placeholder embedding API key detected, using deterministic fallback mock vector", provider=settings.EMBEDDING_PROVIDER)
            return self._generate_mock_vector(text)

        logger.info("Calling embedding API", model=self._model, text_len=len(text))
        try:
            if settings.LLM_PROVIDER == "gemini":
                if not self._client:
                    import google.generativeai as genai
                    genai.configure(api_key=settings.GEMINI_API_KEY)
                    self._client = genai
                
                try:
                    response = await self._client.embed_content_async(
                        model=self._model,
                        content=text,
                        output_dimensionality=768
                    )
                except Exception as model_err:
                    if "not found" in str(model_err).lower() or "404" in str(model_err):
                        logger.warn("Gemini embedding model not found, trying fallbacks", model=self._model, error=str(model_err))
                        fallback_models = ["models/gemini-embedding-2", "models/gemini-embedding-001"]
                        response = None
                        for fallback in fallback_models:
                            try:
                                response = await self._client.embed_content_async(
                                    model=fallback,
                                    content=text,
                                    output_dimensionality=768
                                )
                                self._model = fallback
                                logger.info("Successfully fell back to embedding model", model=fallback)
                                break
                            except Exception as fb_err:
                                logger.warn("Fallback embedding model failed", model=fallback, error=str(fb_err))
                                continue
                        if not response:
                            raise model_err
                    else:
                        raise model_err
                
                if isinstance(response, dict):
                    embed_obj = response.get('embedding', [])
                else:
                    embed_obj = getattr(response, 'embedding', [])
                
                if isinstance(embed_obj, dict) and 'values' in embed_obj:
                    vector = embed_obj['values']
                elif hasattr(embed_obj, 'values'):
                    vector = embed_obj.values
                else:
                    vector = embed_obj
                
                if not isinstance(vector, list):
                    vector = list(vector)
            else:
                kwargs = {
                    "input": text,
                    "model": self._model
                }
                # Azure and OpenAI text-embedding-3-small support the dimensions parameter.
                # The database schema expects EMBEDDING_DIMENSIONS dimensions.
                # Ollama fixes its own output width and rejects the parameter, so skip it there.
                if settings.EMBEDDING_PROVIDER != "ollama" and (
                    "text-embedding-3-" in self._model or settings.EMBEDDING_PROVIDER == "azure"
                ):
                    kwargs["dimensions"] = settings.EMBEDDING_DIMENSIONS
                response = await self._client.embeddings.create(**kwargs)
                vector = response.data[0].embedding
            
            # Save to cache
            try:
                await cache_service.set(cache_key, json.dumps(vector), ttl_seconds=86400)
            except Exception as cache_save_err:
                logger.warn("Failed to cache embedding", error=str(cache_save_err))
                
            return vector
        except Exception as api_err:
            logger.error("Embedding API call failed, running heuristic mock fallback", model=self._model, error=str(api_err))
            return self._generate_mock_vector(text)

    def _generate_mock_vector(self, text: str, dimensions: int = 0) -> List[float]:
        """Generate a deterministic unit-length mock vector for a given text input."""
        import random
        if not dimensions:
            dimensions = settings.EMBEDDING_DIMENSIONS
        text_bytes = text.encode("utf-8")
        h = hashlib.sha256(text_bytes).digest()
        seed = int.from_bytes(h[:4], "big")
        rng = random.Random(seed)
        vector = [rng.uniform(-1.0, 1.0) for _ in range(dimensions)]
        # Normalize to unit length (L2 norm)
        norm = sum(x * x for x in vector) ** 0.5
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector

    async def generate_embedding(self, text: str) -> List[float]:
        """Alias for generate_vector to maintain backward compatibility."""
        return await self.generate_vector(text)

    async def process_scraped_batch(self, limit: int = 50) -> int:
        """
        Fetches unprocessed articles with status SCRAPED, generates their vector representations,
        and persists them. Returns the number of successfully processed articles.
        """
        logger.info("Starting embedding batch process", limit=limit)
        processed_count = 0

        async with AsyncSessionFactory() as session:
            repo = ArticleRepository(session)
            embed_repo = EmbeddingRepository(session)

            try:
                articles_db = await repo.get_unprocessed_articles(limit)
                # Project ORM objects to simple dictionaries immediately to prevent
                # MissingGreenlet / expired object access errors on loop iterations
                # after a rollback.
                articles = [
                    {
                        "id": art.id,
                        "title": art.title,
                        "content": art.content
                    }
                    for art in articles_db
                ]
                logger.info("Fetched unprocessed articles", count=len(articles))

                for article in articles:
                    art_id = article["id"]
                    art_title = article["title"]
                    art_content = article["content"]

                    if not art_content or not art_content.strip():
                        logger.warn("Article content empty, skipping embedding", article_id=str(art_id))
                        continue

                    try:
                        # Title is duplicated and the body capped: see
                        # article_classifier.prepare_embedding_text.
                        text_to_embed = prepare_embedding_text(
                            art_title,
                            art_content,
                            settings.EMBEDDING_MAX_CONTENT_CHARS,
                        )
                        vector = await self.generate_vector(text_to_embed)

                        await embed_repo.create_embedding(
                            article_id=art_id,
                            vector=vector,
                            model_name=self._model
                        )
                        logger.info("Article embedding processed and saved", article_id=str(art_id))
                        processed_count += 1
                    except Exception as article_err:
                        logger.error(
                            "Failed to process embedding for single article",
                            article_id=str(art_id),
                            error=str(article_err)
                        )
                        # Rollback the session for this failed article's transaction
                        await session.rollback()
                        continue

                logger.info("Embedding batch processing completed", processed_count=processed_count)
            except Exception as batch_err:
                logger.error("Embedding batch process encountered a fatal error", error=str(batch_err))
                await session.rollback()

        return processed_count
