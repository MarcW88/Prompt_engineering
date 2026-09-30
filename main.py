#!/usr/bin/env python3
"""
Prompt Finder - Scraping GEO pour découverte de questions utilisateurs
Usage: python main.py --config config/decathlon.yaml
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from utils.config_loader import load_config
from utils.logger import setup_logger, get_logger
from scrapers import ForumScraper, ReviewScraper, SerpScraper
from storage import RawStorage
from filters import QualityFilter
from export import Exporter


def parse_args():
    parser = argparse.ArgumentParser(description="Prompt Finder - Scraping GEO")
    parser.add_argument(
        "--config", "-c",
        default="./config/decathlon.yaml",
        help="Path to client config file (YAML)"
    )
    parser.add_argument(
        "--output", "-o",
        default="./output",
        help="Output directory"
    )
    parser.add_argument(
        "--sources", "-s",
        default=None,
        help="Comma-separated list of sources to scrape (forum,review,serp)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually scrape, just show what would be done"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data for this client before scraping"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logger(log_level, f"{args.output}/logs")
    logger = get_logger("main")
    
    logger.info("=" * 60)
    logger.info("PROMPT FINDER - Starting")
    logger.info("=" * 60)
    
    try:
        config = load_config(args.config)
        logger.info(f"Loaded config for client: {config.client.name}")
        logger.info(f"  - Brand variants: {len(config.brand_variants)}")
        logger.info(f"  - Themes: {len(config.themes)}")
        logger.info(f"  - Markets: {config.markets}")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)
    
    storage = RawStorage(f"{args.output}/raw/scraping.db")
    
    if args.clear:
        logger.warning(f"Clearing existing data for {config.client.slug}")
        storage.clear(config.client.slug)
    
    scrapers = [
        ForumScraper(config),
        ReviewScraper(config),
        SerpScraper(config),
    ]
    
    if args.sources:
        enabled_sources = [s.strip().lower() for s in args.sources.split(",")]
        scrapers = [s for s in scrapers if s.source_type in enabled_sources]
        logger.info(f"Filtering to sources: {enabled_sources}")
    
    if args.dry_run:
        logger.info("DRY RUN - No scraping will be performed")
        for scraper in scrapers:
            status = "ENABLED" if scraper.is_enabled else "DISABLED"
            logger.info(f"  - {scraper.__class__.__name__}: {status}")
        return
    
    logger.info("-" * 40)
    logger.info("PHASE 1: Scraping")
    logger.info("-" * 40)
    
    total_items = 0
    all_stats = []
    
    for scraper in scrapers:
        if not scraper.is_enabled:
            logger.info(f"Skipping {scraper.__class__.__name__} (disabled)")
            continue
        
        logger.info(f"Running {scraper.__class__.__name__}...")
        
        try:
            items = scraper.run()
            saved = storage.save(items)
            total_items += saved
            
            stats = scraper.get_stats()
            all_stats.append(stats)
            
            logger.info(f"  → Scraped: {stats['items_scraped']}, Saved: {saved}, Errors: {stats['errors_count']}")
            
        except Exception as e:
            logger.error(f"Error in {scraper.__class__.__name__}: {e}")
    
    logger.info("-" * 40)
    logger.info("PHASE 2: Filtering")
    logger.info("-" * 40)
    
    all_items = storage.get_all({"client_slug": config.client.slug})
    logger.info(f"Total items in storage: {len(all_items)}")
    
    quality_filter = QualityFilter(config)
    filter_result = quality_filter.filter(all_items)
    
    logger.info(f"  → Accepted: {len(filter_result.accepted)}")
    logger.info(f"  → Rejected: {len(filter_result.rejected)}")
    
    if filter_result.stats["rejection_reasons"]:
        logger.info("  → Rejection reasons:")
        for reason, count in filter_result.stats["rejection_reasons"].items():
            logger.info(f"      - {reason}: {count}")
    
    logger.info("-" * 40)
    logger.info("PHASE 3: Export")
    logger.info("-" * 40)
    
    exporter = Exporter(config, args.output)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    client_slug = config.client.slug
    
    if config.output.format == "json":
        output_file = exporter.to_json(
            filter_result.accepted,
            f"{client_slug}_corpus_{timestamp}.json"
        )
    else:
        output_file = exporter.to_csv(
            filter_result.accepted,
            f"{client_slug}_corpus_{timestamp}.csv"
        )
    
    if config.output.include_rejected and filter_result.rejected:
        exporter.export_rejected(
            filter_result.rejected,
            f"{client_slug}_rejected_{timestamp}.csv"
        )
    
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Client: {config.client.name}")
    logger.info(f"Total scraped: {total_items}")
    logger.info(f"Total accepted: {len(filter_result.accepted)}")
    logger.info(f"Total rejected: {len(filter_result.rejected)}")
    logger.info(f"Output: {output_file}")
    logger.info("=" * 60)
    
    storage_stats = storage.get_stats()
    logger.info("Storage stats:")
    logger.info(f"  - Total items: {storage_stats['total_items']}")
    logger.info(f"  - By source: {storage_stats['by_source_type']}")
    logger.info(f"  - By platform: {storage_stats['by_platform']}")


if __name__ == "__main__":
    main()
