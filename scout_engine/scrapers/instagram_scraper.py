"""
Instagram Location Scraper for The Afters
Scrapes recent media from Instagram location pages using Playwright
"""

import asyncio
import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Browser

load_dotenv()


@dataclass
class MediaItem:
    """Represents a scraped media item from Instagram"""
    url: str
    thumbnail_url: str
    media_type: str  # 'image' or 'video'
    shortcode: str
    scraped_at: str


@dataclass
class ScrapeResult:
    """Result of a location scrape"""
    location_url: str
    location_name: Optional[str]
    media_items: list[MediaItem]
    scraped_at: str
    success: bool
    error: Optional[str] = None


class InstagramLocationScraper:
    """Scrapes Instagram location pages for recent media"""

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url or os.getenv("PROXY_URL")
        self.scrape_delay = float(os.getenv("SCRAPE_DELAY_SECONDS", "3"))
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))

    async def _setup_browser(self) -> tuple[Browser, any]:
        """Set up Playwright browser with anti-detection measures"""
        playwright = await async_playwright().start()

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]

        launch_options = {
            "headless": True,
            "args": browser_args,
        }

        if self.proxy_url:
            launch_options["proxy"] = {"server": self.proxy_url}

        browser = await playwright.chromium.launch(**launch_options)
        return browser, playwright

    async def _create_stealth_context(self, browser: Browser):
        """Create a browser context with realistic fingerprints"""
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )

        # Add stealth scripts
        await context.add_init_script("""
            // Mask webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Mask automation
            window.chrome = { runtime: {} };

            // Mask permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

        return context

    async def _extract_media_from_page(self, page: Page, max_items: int = 10) -> list[MediaItem]:
        """Extract media URLs from loaded Instagram location page"""
        media_items = []

        # Wait for posts to load
        await page.wait_for_timeout(2000)

        # Try to find post links - Instagram uses article elements or divs with specific structure
        # The posts are typically in a grid layout
        post_links = await page.query_selector_all('a[href*="/p/"]')

        seen_shortcodes = set()

        for link in post_links[:max_items * 2]:  # Get extra in case of duplicates
            if len(media_items) >= max_items:
                break

            try:
                href = await link.get_attribute("href")
                if not href:
                    continue

                # Extract shortcode from URL
                match = re.search(r'/p/([A-Za-z0-9_-]+)', href)
                if not match:
                    continue

                shortcode = match.group(1)

                if shortcode in seen_shortcodes:
                    continue
                seen_shortcodes.add(shortcode)

                # Try to get thumbnail image from within the link
                img = await link.query_selector("img")
                thumbnail_url = ""
                if img:
                    thumbnail_url = await img.get_attribute("src") or ""

                # Determine if it's a video (look for video icon overlay)
                video_indicator = await link.query_selector('svg[aria-label*="Video"], svg[aria-label*="Reel"]')
                media_type = "video" if video_indicator else "image"

                # Construct full URL
                full_url = f"https://www.instagram.com/p/{shortcode}/"

                media_items.append(MediaItem(
                    url=full_url,
                    thumbnail_url=thumbnail_url,
                    media_type=media_type,
                    shortcode=shortcode,
                    scraped_at=datetime.utcnow().isoformat()
                ))

            except Exception as e:
                print(f"Error extracting media item: {e}")
                continue

        return media_items

    async def _get_location_name(self, page: Page) -> Optional[str]:
        """Extract the location name from the page"""
        try:
            # Try to find the location header
            header = await page.query_selector('h1')
            if header:
                return await header.inner_text()
        except Exception:
            pass
        return None

    async def scrape_location(self, location_url: str, max_items: int = 10) -> ScrapeResult:
        """
        Scrape recent media from an Instagram location page

        Args:
            location_url: Full Instagram location URL
                         (e.g., https://www.instagram.com/explore/locations/123456/venue-name/)
            max_items: Maximum number of media items to scrape (default 10)

        Returns:
            ScrapeResult with media items or error
        """
        browser = None
        playwright = None

        for attempt in range(self.max_retries):
            try:
                browser, playwright = await self._setup_browser()
                context = await self._create_stealth_context(browser)
                page = await context.new_page()

                # Add random delay to seem more human
                await asyncio.sleep(random.uniform(1, self.scrape_delay))

                # Navigate to location page
                print(f"Navigating to: {location_url} (attempt {attempt + 1})")
                response = await page.goto(location_url, wait_until="networkidle", timeout=30000)

                if response and response.status == 429:
                    print("Rate limited! Waiting before retry...")
                    await asyncio.sleep(30 * (attempt + 1))
                    continue

                if response and response.status != 200:
                    raise Exception(f"HTTP {response.status}")

                # Check for login wall
                login_wall = await page.query_selector('input[name="username"]')
                if login_wall:
                    print("Login wall detected - Instagram is blocking anonymous access")
                    raise Exception("Login required - Instagram blocking anonymous scraping")

                # Extract location name
                location_name = await self._get_location_name(page)

                # Extract media items
                media_items = await self._extract_media_from_page(page, max_items)

                if not media_items:
                    # Try scrolling to load more content
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)
                    media_items = await self._extract_media_from_page(page, max_items)

                await browser.close()
                await playwright.stop()

                return ScrapeResult(
                    location_url=location_url,
                    location_name=location_name,
                    media_items=media_items,
                    scraped_at=datetime.utcnow().isoformat(),
                    success=True
                )

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if browser:
                    await browser.close()
                if playwright:
                    await playwright.stop()

                if attempt == self.max_retries - 1:
                    return ScrapeResult(
                        location_url=location_url,
                        location_name=None,
                        media_items=[],
                        scraped_at=datetime.utcnow().isoformat(),
                        success=False,
                        error=str(e)
                    )

                # Wait before retry
                await asyncio.sleep(5 * (attempt + 1))

        return ScrapeResult(
            location_url=location_url,
            location_name=None,
            media_items=[],
            scraped_at=datetime.utcnow().isoformat(),
            success=False,
            error="Max retries exceeded"
        )


def result_to_dict(result: ScrapeResult) -> dict:
    """Convert ScrapeResult to JSON-serializable dict"""
    return {
        "location_url": result.location_url,
        "location_name": result.location_name,
        "media_items": [
            {
                "url": item.url,
                "thumbnail_url": item.thumbnail_url,
                "media_type": item.media_type,
                "shortcode": item.shortcode,
                "scraped_at": item.scraped_at
            }
            for item in result.media_items
        ],
        "scraped_at": result.scraped_at,
        "success": result.success,
        "error": result.error
    }


async def main():
    """CLI entry point for testing"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python instagram_scraper.py <location_url> [max_items]")
        print("Example: python instagram_scraper.py https://www.instagram.com/explore/locations/123456/venue-name/")
        sys.exit(1)

    location_url = sys.argv[1]
    max_items = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    scraper = InstagramLocationScraper()
    result = await scraper.scrape_location(location_url, max_items)

    print(json.dumps(result_to_dict(result), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
