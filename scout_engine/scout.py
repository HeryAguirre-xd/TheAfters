#!/usr/bin/env python3
"""
Scout Engine - Main Runner for The Afters
Scrapes Instagram locations and analyzes vibes in one pipeline
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scout_engine.scrapers.instagram_scraper import (
    InstagramLocationScraper,
    ScrapeResult,
    result_to_dict
)
from scout_engine.analyzers.vibe_analyzer import (
    VibeAnalyzer,
    VibeAnalysis,
    analysis_to_dict
)

load_dotenv()


class ScoutEngine:
    """
    Complete Scout pipeline:
    1. Scrape Instagram location for recent media
    2. Analyze thumbnails with Claude Vision
    3. Return combined vibe report
    """

    def __init__(self, anthropic_api_key: Optional[str] = None):
        self.scraper = InstagramLocationScraper()
        self.analyzer = VibeAnalyzer(api_key=anthropic_api_key)

    async def scout_location(
        self,
        location_url: str,
        max_posts: int = 10,
        analyze_images: bool = True
    ) -> dict:
        """
        Run the full Scout pipeline on a location

        Args:
            location_url: Instagram location URL
            max_posts: Maximum posts to scrape (default 10)
            analyze_images: Whether to run Claude Vision analysis (default True)

        Returns:
            Complete vibe report as dict
        """
        print(f"\n{'='*60}")
        print(f"SCOUT ENGINE - The Afters")
        print(f"{'='*60}")
        print(f"Target: {location_url}")
        print(f"Max posts: {max_posts}")
        print(f"{'='*60}\n")

        # Step 1: Scrape the location
        print("[1/3] Scraping Instagram location...")
        scrape_result = await self.scraper.scrape_location(location_url, max_posts)

        if not scrape_result.success:
            return {
                "success": False,
                "error": scrape_result.error,
                "location_url": location_url,
                "scraped_at": scrape_result.scraped_at
            }

        print(f"      Found {len(scrape_result.media_items)} posts")

        if not scrape_result.media_items:
            return {
                "success": True,
                "location_url": location_url,
                "location_name": scrape_result.location_name,
                "post_count": 0,
                "vibe_summary": None,
                "message": "No posts found at this location",
                "scraped_at": scrape_result.scraped_at
            }

        # Step 2: Analyze thumbnails with Claude Vision
        analyses = []
        if analyze_images:
            print("[2/3] Analyzing vibes with Claude Vision...")

            # Get thumbnail URLs
            thumbnail_urls = [
                item.thumbnail_url
                for item in scrape_result.media_items
                if item.thumbnail_url
            ]

            if thumbnail_urls:
                analyses = await self.analyzer.analyze_batch(thumbnail_urls, concurrency=2)
                successful_analyses = [a for a in analyses if a.success]
                print(f"      Analyzed {len(successful_analyses)}/{len(thumbnail_urls)} images")
            else:
                print("      No thumbnails available for analysis")
        else:
            print("[2/3] Skipping vibe analysis (disabled)")

        # Step 3: Aggregate results
        print("[3/3] Generating vibe report...")

        vibe_summary = self._aggregate_vibes(analyses) if analyses else None

        report = {
            "success": True,
            "location_url": location_url,
            "location_name": scrape_result.location_name,
            "post_count": len(scrape_result.media_items),
            "scraped_at": scrape_result.scraped_at,
            "posts": [
                {
                    "url": item.url,
                    "thumbnail_url": item.thumbnail_url,
                    "media_type": item.media_type,
                    "shortcode": item.shortcode
                }
                for item in scrape_result.media_items
            ],
            "analyses": [analysis_to_dict(a) for a in analyses] if analyses else [],
            "vibe_summary": vibe_summary
        }

        print(f"\n{'='*60}")
        print("VIBE REPORT")
        print(f"{'='*60}")
        if vibe_summary:
            print(f"Energy Level: {vibe_summary['avg_energy']}/10")
            print(f"Crowd Level:  {vibe_summary['avg_crowd']}/10")
            print(f"Top Vibes:    {', '.join(vibe_summary['top_vibe_tags'])}")
            print(f"Status:       {vibe_summary['status']}")
        else:
            print("No vibe data available")
        print(f"{'='*60}\n")

        return report

    def _aggregate_vibes(self, analyses: list[VibeAnalysis]) -> dict:
        """Aggregate multiple analyses into a summary"""
        successful = [a for a in analyses if a.success and a.confidence > 0.3]

        if not successful:
            return {
                "avg_energy": 5,
                "avg_crowd": 5,
                "top_vibe_tags": ["Unknown"],
                "status": "insufficient_data",
                "sample_size": 0
            }

        # Calculate averages
        avg_energy = sum(a.energy_level for a in successful) / len(successful)
        avg_crowd = sum(a.crowd_level for a in successful) / len(successful)

        # Count vibe tags
        tag_counts = {}
        for analysis in successful:
            for tag in analysis.vibe_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Get top tags
        top_tags = sorted(tag_counts.keys(), key=lambda t: tag_counts[t], reverse=True)[:4]

        # Determine status
        if avg_energy >= 7 and avg_crowd >= 7:
            status = "LIVE"
        elif avg_energy >= 5 or avg_crowd >= 5:
            status = "warming_up"
        else:
            status = "dead"

        return {
            "avg_energy": round(avg_energy, 1),
            "avg_crowd": round(avg_crowd, 1),
            "top_vibe_tags": top_tags if top_tags else ["Unknown"],
            "status": status,
            "sample_size": len(successful)
        }


async def main():
    """CLI entry point"""
    if len(sys.argv) < 2:
        print("""
Scout Engine - The Afters
=========================

Usage: python scout.py <instagram_location_url> [options]

Arguments:
    instagram_location_url    Full Instagram location URL

Options:
    --max-posts=N            Maximum posts to scrape (default: 10)
    --no-analyze             Skip Claude Vision analysis
    --output=FILE            Save JSON output to file

Examples:
    python scout.py https://www.instagram.com/explore/locations/123456/club-name/
    python scout.py https://www.instagram.com/explore/locations/123456/club-name/ --max-posts=5
    python scout.py https://www.instagram.com/explore/locations/123456/club-name/ --output=report.json

Required Environment Variables:
    ANTHROPIC_API_KEY        Your Claude API key (for vibe analysis)

Optional Environment Variables:
    PROXY_URL                Proxy server for scraping
    SCRAPE_DELAY_SECONDS     Delay between requests (default: 3)
""")
        sys.exit(1)

    location_url = sys.argv[1]
    max_posts = 10
    analyze = True
    output_file = None

    # Parse options
    for arg in sys.argv[2:]:
        if arg.startswith("--max-posts="):
            max_posts = int(arg.split("=")[1])
        elif arg == "--no-analyze":
            analyze = False
        elif arg.startswith("--output="):
            output_file = arg.split("=")[1]

    try:
        engine = ScoutEngine()
        report = await engine.scout_location(location_url, max_posts, analyze)

        output_json = json.dumps(report, indent=2)

        if output_file:
            with open(output_file, "w") as f:
                f.write(output_json)
            print(f"Report saved to: {output_file}")
        else:
            print("\nFull JSON Report:")
            print(output_json)

    except ValueError as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
