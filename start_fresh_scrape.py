#!/usr/bin/env python3
"""
Start a Fresh Apify Scrape
This will trigger a new scrape of your target Shopify store
"""

import os
import sys
from dotenv import load_dotenv
from services.apify_service import ApifyService
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    load_dotenv()

    apify_token = os.getenv('APIFY_API_TOKEN')
    if not apify_token:
        logger.error("❌ APIFY_API_TOKEN not found")
        return 1

    # Ask user which website to scrape
    print("\n" + "=" * 80)
    print("🚀 START FRESH APIFY SCRAPE")
    print("=" * 80)
    print("\nWhich website should we scrape products from?")
    print("\nExamples:")
    print("  - https://safetysuppliesco.co.uk")
    print("  - https://www.flooringsuppliesuk.com")
    print("  - https://example-store.myshopify.com")
    print("\n" + "=" * 80)

    target_url = input("\n🎯 Enter the website URL to scrape: ").strip()

    if not target_url:
        logger.error("❌ No URL provided")
        return 1

    # Add https:// if missing
    if not target_url.startswith('http'):
        target_url = 'https://' + target_url

    print(f"\n✅ Target URL: {target_url}")

    # Ask for max products
    max_products_input = input("\n📦 How many products to scrape? (default: 200): ").strip()
    max_products = int(max_products_input) if max_products_input else 200

    print(f"\n✅ Max products: {max_products}")
    print("\n" + "=" * 80)
    print("🚀 STARTING APIFY SCRAPER...")
    print("=" * 80 + "\n")

    # Start scraper
    apify_service = ApifyService(apify_token)

    try:
        run_id = apify_service.start_scraper(target_url, max_results=max_products)

        if run_id:
            print(f"\n✅ Scraper started successfully!")
            print(f"🆔 Run ID: {run_id}")
            print(f"\n🔗 Monitor progress at:")
            print(f"   https://console.apify.com/actors/runs/{run_id}")
            print(f"\n⏱️  This will take a few minutes...")
            print(f"\n💡 TIP: Use your web app's /scrape-last endpoint to fetch")
            print(f"   products once the scrape completes!")
            return 0
        else:
            logger.error("❌ Failed to start scraper")
            return 1

    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
