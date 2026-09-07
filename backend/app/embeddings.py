import time

import voyageai

from app.config import settings


EMBEDDING_MODEL = "voyage-code-3"
EMBEDDING_DIM = 1024

_client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Create embeddings while respecting the free Voyage rate limits."""
    all_embeddings: list[list[float]] = []

    # Keep each request very small because the free account
    # has a 10K tokens-per-minute limit.
    batch_size = 2

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        result = _client.embed(
            batch,
            model=EMBEDDING_MODEL,
            input_type="document",
            output_dimension=EMBEDDING_DIM,
        )

        all_embeddings.extend(result.embeddings)

        # Stay below the free-account request rate of 3 RPM.
        if i + batch_size < len(texts):
            time.sleep(21)

    return all_embeddings


def embed_query(text: str) -> list[float]:
    """Create an embedding for a search query while respecting free-tier rate limits."""
    result = _client.embed(
        [text],
        model=EMBEDDING_MODEL,
        input_type="query",
        output_dimension=EMBEDDING_DIM,
    )

    # Free Voyage accounts are limited to 3 requests per minute.
    time.sleep(21)

    return result.embeddings[0]