#!/usr/bin/env python3
"""
Diagnose Apify Integration Issues
This script provides detailed information about the last Apify run
"""

import os
import sys
from dotenv import load_dotenv
from services.apify_service import ApifyService
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Load environment variables
    load_dotenv()

    apify_token = os.getenv('APIFY_API_TOKEN')
    if not apify_token:
        logger.error("❌ APIFY_API_TOKEN not found in environment variables")
        return 1

    logger.info("=" * 80)
    logger.info("🔍 APIFY DIAGNOSTIC TOOL")
    logger.info("=" * 80)

    # Initialize service
    apify_service = ApifyService(apify_token)

    logger.info(f"\n📋 Actor ID: {apify_service.actor_id}")
    logger.info(f"🔗 Base URL: {apify_service.base_url}")

    # Get last run info with detailed logging
    logger.info("\n" + "=" * 80)
    logger.info("📊 FETCHING LAST RUN INFORMATION")
    logger.info("=" * 80 + "\n")

    run_id, status = apify_service.get_last_run()

    if not run_id:
        logger.error("❌ Could not retrieve last run information")
        return 1

    # Get detailed run data
    logger.info("\n" + "=" * 80)
    logger.info("📦 CHECKING DATASET")
    logger.info("=" * 80 + "\n")

    # Try to fetch products with detailed logging
    logger.info("\n" + "=" * 80)
    logger.info("🎯 FETCHING PRODUCTS")
    logger.info("=" * 80 + "\n")

    products = apify_service.get_last_run_data(limit=10)

    if products:
        logger.info(f"\n✅ SUCCESS! Fetched {len(products)} product(s)")
        logger.info("\n📦 SAMPLE PRODUCT DATA:")
        if len(products) > 0:
            sample = products[0]
            logger.info(f"  Title: {sample.get('title', 'N/A')}")
            logger.info(f"  URL: {sample.get('url', 'N/A')}")
            logger.info(f"  Price: {sample.get('price', 'N/A')}")
            logger.info(f"  Variants: {len(sample.get('variants', []))}")
    else:
        logger.error("\n❌ NO PRODUCTS FOUND")
        logger.error("\nPossible reasons:")
        logger.error("  1. The last Apify run didn't scrape any products")
        logger.error("  2. The website might be blocking the scraper")
        logger.error("  3. The Apify actor configuration might need adjustment")
        logger.error("  4. The website structure might have changed")
        logger.error("\n💡 Recommended action:")
        logger.error("  - Check the Apify console: https://console.apify.com/actors/runs")
        logger.error(f"  - View run details: https://console.apify.com/actors/runs/{run_id}")
        logger.error("  - Try starting a new scrape run with /scrape endpoint")

    logger.info("\n" + "=" * 80)
    logger.info("🏁 DIAGNOSTIC COMPLETE")
    logger.info("=" * 80)

    return 0

if __name__ == "__main__":
    sys.exit(main())
