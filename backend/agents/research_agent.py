"""
Research Agent: searches the web via Tavily and ingests uploaded documents.
Stores raw sources in obsidian-vault/raw/ (immutable).
"""
import os
import uuid
import httpx
from pathlib import Path
from wiki.manager import save_raw_source
from wiki.confidence import (get_domain_score, compute_corroboration,
                              compute_final_confidence, get_confidence_tier)
from models.schemas import Source, ConfidenceTier
from datetime import datetime

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
UPLOADS_PATH = Path(os.getenv("UPLOADS_PATH", "./obsidian-vault/uploads"))


async def research_topic(topic: str, num_sources: int = 5,
                          depth: str = "basic") -> list[Source]:
    """Search for sources on a topic using Tavily. Returns evaluated Source objects."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": topic,
                "search_depth": depth,
                "max_results": num_sources,
                "include_raw_content": True,
            },
            timeout=30.0
        )
        response.raise_for_status()
        results = response.json().get("results", [])

    sources = []
    all_contents = [r.get("content", "") for r in results]

    for r in results:
        source_id = str(uuid.uuid4())[:8]
        url = r.get("url", "")
        content = r.get("content", "") or r.get("raw_content", "")
        title = r.get("title", url)

        credibility = get_domain_score(url)
        other_contents = [c for c in all_contents if c != content]
        corroboration = compute_corroboration(content, other_contents)
        final_conf = compute_final_confidence(credibility, corroboration)
        tier = get_confidence_tier(final_conf)

        if content:
            save_raw_source(title, f"# {title}\nURL: {url}\n\n{content}", source_id)

        flagged_reason = None
        if tier == ConfidenceTier.low:
            if credibility < 0.50:
                flagged_reason = f"Low-credibility domain ({url.split('/')[2] if '/' in url else url})"
            else:
                flagged_reason = "Not corroborated by other sources"
        elif tier == ConfidenceTier.discard:
            flagged_reason = "Very low credibility — excluded from wiki"

        sources.append(Source(
            id=source_id,
            url=url,
            title=title,
            domain=url.split("/")[2] if url.startswith("http") else None,
            credibility_score=credibility,
            corroboration_score=corroboration,
            final_confidence=final_conf,
            confidence_tier=tier,
            scraped_at=datetime.now().isoformat(),
            content_preview=content[:200],
            flagged_reason=flagged_reason
        ))

    return sources


def create_source_from_text(title: str, text: str) -> Source:
    """Create a Source object from user-pasted raw text."""
    source_id = str(uuid.uuid4())[:8]
    return Source(
        id=source_id,
        title=title,
        credibility_score=0.85,
        corroboration_score=0.75,
        final_confidence=0.85,
        confidence_tier=get_confidence_tier(0.85),
        scraped_at=datetime.now().isoformat(),
        content_preview=text[:4000],
    )


async def ingest_uploaded_file(file_path: str, filename: str) -> Source:
    """Ingest a manually uploaded document."""
    source_id = str(uuid.uuid4())[:8]
    content = Path(file_path).read_text(encoding="utf-8", errors="ignore")[:5000]

    credibility = 0.80
    final_conf = 0.80
    tier = get_confidence_tier(final_conf)

    return Source(
        id=source_id,
        file_path=file_path,
        title=filename,
        credibility_score=credibility,
        corroboration_score=0.5,
        final_confidence=final_conf,
        confidence_tier=tier,
        scraped_at=datetime.now().isoformat(),
        content_preview=content[:200]
    )
