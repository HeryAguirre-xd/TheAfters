"""
Vibe Analyzer - Claude Vision Integration for The Afters
Analyzes venue images to extract energy levels and vibe tags
"""

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from typing import Optional

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


@dataclass
class VibeAnalysis:
    """Result of analyzing a single image"""
    image_url: str
    energy_level: int  # 1-10
    crowd_level: int   # 1-10
    vibe_tags: list[str]  # e.g., ["Techno", "Dark", "Packed"]
    description: str
    confidence: float  # 0-1
    success: bool
    error: Optional[str] = None


class VibeAnalyzer:
    """Analyzes venue images using Claude Vision API"""

    VIBE_PROMPT = """You are analyzing a social media image/thumbnail from a nightlife venue to determine the current vibe and energy.

Analyze this image and respond with ONLY a JSON object (no markdown, no explanation) in this exact format:
{
    "energy_level": <1-10 integer>,
    "crowd_level": <1-10 integer>,
    "vibe_tags": [<list of 2-4 descriptive tags>],
    "description": "<one sentence describing the scene>",
    "confidence": <0.0-1.0 float>
}

Scoring guide:
- energy_level: 1=empty/dead, 5=moderate activity, 10=absolutely packed and wild
- crowd_level: 1=empty, 5=half capacity, 10=shoulder to shoulder
- vibe_tags: Choose from or similar to: "Techno", "House", "Hip-Hop", "Latin", "Chill", "Hype", "Dark", "Bright", "Intimate", "Massive", "VIP", "Underground", "Mainstream", "Live Music", "DJ Set", "Dancing", "Lounge"
- confidence: How confident you are in this assessment (low if image is blurry, unclear, or not of a venue)

If the image is not of a venue/party scene, still provide your best guess but set confidence low.
Respond with ONLY the JSON object, nothing else."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found. Set it in .env or pass api_key parameter. "
                "Get your key at: https://console.anthropic.com/settings/keys"
            )
        self.client = Anthropic(api_key=self.api_key)

    async def _fetch_image_as_base64(self, image_url: str) -> tuple[str, str]:
        """Fetch an image and convert to base64"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                image_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
                follow_redirects=True,
                timeout=30.0
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "image/jpeg")
            if "jpeg" in content_type or "jpg" in content_type:
                media_type = "image/jpeg"
            elif "png" in content_type:
                media_type = "image/png"
            elif "gif" in content_type:
                media_type = "image/gif"
            elif "webp" in content_type:
                media_type = "image/webp"
            else:
                media_type = "image/jpeg"  # default assumption

            base64_data = base64.standard_b64encode(response.content).decode("utf-8")
            return base64_data, media_type

    def _parse_response(self, response_text: str, image_url: str) -> VibeAnalysis:
        """Parse Claude's JSON response into VibeAnalysis"""
        try:
            # Clean up response - remove any markdown formatting if present
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            data = json.loads(text)

            return VibeAnalysis(
                image_url=image_url,
                energy_level=max(1, min(10, int(data.get("energy_level", 5)))),
                crowd_level=max(1, min(10, int(data.get("crowd_level", 5)))),
                vibe_tags=data.get("vibe_tags", [])[:4],
                description=data.get("description", "Unable to analyze"),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                success=True
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return VibeAnalysis(
                image_url=image_url,
                energy_level=5,
                crowd_level=5,
                vibe_tags=["Unknown"],
                description="Failed to parse analysis",
                confidence=0.0,
                success=False,
                error=f"Parse error: {e}"
            )

    async def analyze_image(self, image_url: str) -> VibeAnalysis:
        """
        Analyze a single image URL using Claude Vision

        Args:
            image_url: URL of the image to analyze

        Returns:
            VibeAnalysis with energy level, crowd level, and vibe tags
        """
        try:
            # Fetch and encode image
            base64_data, media_type = await self._fetch_image_as_base64(image_url)

            # Call Claude Vision API
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_data
                                }
                            },
                            {
                                "type": "text",
                                "text": self.VIBE_PROMPT
                            }
                        ]
                    }
                ]
            )

            response_text = message.content[0].text
            return self._parse_response(response_text, image_url)

        except httpx.HTTPError as e:
            return VibeAnalysis(
                image_url=image_url,
                energy_level=5,
                crowd_level=5,
                vibe_tags=["Unknown"],
                description="Failed to fetch image",
                confidence=0.0,
                success=False,
                error=f"HTTP error: {e}"
            )

        except Exception as e:
            return VibeAnalysis(
                image_url=image_url,
                energy_level=5,
                crowd_level=5,
                vibe_tags=["Unknown"],
                description="Analysis failed",
                confidence=0.0,
                success=False,
                error=str(e)
            )

    async def analyze_batch(
        self,
        image_urls: list[str],
        concurrency: int = 3
    ) -> list[VibeAnalysis]:
        """
        Analyze multiple images with controlled concurrency

        Args:
            image_urls: List of image URLs to analyze
            concurrency: Max concurrent API calls (be mindful of rate limits)

        Returns:
            List of VibeAnalysis results
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def analyze_with_limit(url: str) -> VibeAnalysis:
            async with semaphore:
                result = await self.analyze_image(url)
                # Small delay between requests to respect rate limits
                await asyncio.sleep(0.5)
                return result

        tasks = [analyze_with_limit(url) for url in image_urls]
        return await asyncio.gather(*tasks)


def analysis_to_dict(analysis: VibeAnalysis) -> dict:
    """Convert VibeAnalysis to JSON-serializable dict"""
    return {
        "image_url": analysis.image_url,
        "energy_level": analysis.energy_level,
        "crowd_level": analysis.crowd_level,
        "vibe_tags": analysis.vibe_tags,
        "description": analysis.description,
        "confidence": analysis.confidence,
        "success": analysis.success,
        "error": analysis.error
    }


async def main():
    """CLI entry point for testing"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python vibe_analyzer.py <image_url> [image_url2] ...")
        print("Example: python vibe_analyzer.py https://example.com/image.jpg")
        sys.exit(1)

    image_urls = sys.argv[1:]

    try:
        analyzer = VibeAnalyzer()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Analyzing {len(image_urls)} image(s)...")

    if len(image_urls) == 1:
        result = await analyzer.analyze_image(image_urls[0])
        print(json.dumps(analysis_to_dict(result), indent=2))
    else:
        results = await analyzer.analyze_batch(image_urls)
        output = [analysis_to_dict(r) for r in results]
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
