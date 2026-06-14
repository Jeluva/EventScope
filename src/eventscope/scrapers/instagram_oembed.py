"""Instagram — Meta oEmbed Read enrichment.

IMPORTANT — what this can and cannot do (per the product requirement):
  * oEmbed CANNOT discover or list a profile's posts. It only resolves a known
    *permalink* to an embed + caption + thumbnail + author.
  * Therefore IG is modeled as an ENRICHMENT step, not a discovery DAG. The
    permalinks it consumes come from (a) a manual seed list and (b) links
    harvested by the venue/government scrapers.
  * As of April 2025 the unauthenticated oEmbed endpoint was removed. The Graph
    API oEmbed Read endpoint requires a Meta app access token with `oembed_read`.
    When no token is configured, EventScope degrades gracefully to the public
    iframe embed (`/p/{shortcode}/embed/`) — no caption, but a valid embed.

``parse`` operates on an oEmbed JSON response, so it is fully fixture-testable.
"""
from __future__ import annotations

import re
from typing import Any

from ..config import get_settings
from .base import BaseScraper, ScrapedItem, register

GRAPH_OEMBED = "https://graph.facebook.com/v19.0/instagram_oembed"
SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel|tv)/([\w-]+)", re.I)


def shortcode_from_permalink(permalink: str) -> str | None:
    m = SHORTCODE_RE.search(permalink)
    return m.group(1) if m else None


def fallback_embed_html(permalink: str) -> str:
    """Public iframe embed — works without a token, but yields no caption."""
    permalink = permalink.rstrip("/")
    return (
        f'<iframe class="instagram-media" '
        f'src="{permalink}/embed/" width="400" height="480" '
        f'frameborder="0" scrolling="no" allowtransparency="true"></iframe>'
    )


@register
class InstagramOembedScraper(BaseScraper):
    name = "instagram_oembed"
    discovery = False  # enrichment only — cannot list a profile's posts

    def parse(self, raw: dict[str, Any]) -> list[ScrapedItem]:
        """Build a ScrapedItem from one oEmbed response.

        The permalink must be supplied via ``options['permalink']`` or carried in
        the response under ``"_permalink"`` (we stamp it during ``fetch``).
        """
        permalink = self.options.get("permalink") or raw.get("_permalink") or raw.get("author_url", "")
        # oEmbed puts the caption in `title` for Instagram posts.
        caption = raw.get("title") or ""
        author = raw.get("author_name") or ""
        text = "\n".join(p for p in (author, caption) if p)
        return [
            ScrapedItem(
                source="instagram",
                source_url=permalink,
                raw_text=text,
                external_id=shortcode_from_permalink(permalink) or permalink or None,
                image_url=raw.get("thumbnail_url"),
                hints={"author_name": author} if author else {},
                payload={
                    "oembed": raw,
                    "embed_html": raw.get("html") or fallback_embed_html(permalink),
                },
            )
        ]

    def enrich(self, permalinks: list[str]) -> list[ScrapedItem]:  # pragma: no cover - live path
        """Resolve a batch of permalinks. Uses the token when present, else the
        public iframe fallback (which still yields a usable, attributed embed)."""
        token = self.options.get("access_token") or get_settings().ig_access_token
        items: list[ScrapedItem] = []
        if not token:
            for permalink in permalinks:
                items.append(
                    ScrapedItem(
                        source="instagram",
                        source_url=permalink,
                        raw_text="",  # no caption without the API
                        external_id=shortcode_from_permalink(permalink) or permalink,
                        payload={"embed_html": fallback_embed_html(permalink), "fallback": True},
                    )
                )
            return items

        with self._client() as client:
            for permalink in permalinks:
                resp = client.get(
                    GRAPH_OEMBED,
                    params={"url": permalink, "access_token": token, "omitscript": "true"},
                )
                resp.raise_for_status()
                data = resp.json()
                data["_permalink"] = permalink
                items.extend(self.parse(data))
        return items
