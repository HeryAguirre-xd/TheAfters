# The Afters - Project Context

## Vision
A real-time "Vibe Map" for 22-year-olds to find the best party energy in the city. We use social media signals (IG/TikTok location tags) to determine if a place is "Live" or "Dead."

## Tech Stack
- **Backend:** Python (Playwright for scraping, FastAPI for the internal engine)
- **AI:** Claude Vision API (for analyzing vibes from thumbnails)
- **Frontend:** Next.js + Mapbox (for the "Glow Map")
- **Database:** Supabase (PostgreSQL + Real-time)

## Core Workflows
1. **The Scout:** Scrape recent media from 20 top local venue location URLs.
2. **The Vibe Check:** Pass media to Claude Vision to categorize (Energy: 1-10, Crowd: 1-10, Vibe: "Techno/Chill/Hype").
3. **The Pulse:** Update the map markers in real-time.

## Project Rules
- **Speed over Perfection:** Use simple bash scripts and cron jobs first.
- **Agentic Debugging:** If a scraper gets blocked, Claude should automatically suggest and implement a proxy rotation or a new scraping strategy.
- **Main Character Aesthetic:** The UI should look like a "Heat Map," not a spreadsheet.
