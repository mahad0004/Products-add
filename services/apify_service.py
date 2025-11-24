"""
Apify Service
Handles Apify API interactions for Shopify scraping
"""

import requests
import time
import logging

logger = logging.getLogger(__name__)


class ApifyService:
    """Service for interacting with Apify API"""

    def __init__(self, api_token):
        self.api_token = api_token
        self.base_url = "https://api.apify.com/v2"
        self.actor_id = "autofacts~shopify"

    def start_scraper(self, shopify_url, max_results=200):
        """
        Start the Apify Shopify scraper
        Returns: run_id
        """
        url = f"{self.base_url}/acts/{self.actor_id}/runs"

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        # Configure scraper with UK proxy for accurate pricing and availability
        payload = {
            "startUrls": [{"url": shopify_url}],
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
                "apifyProxyCountry": "GB"  # 🇬🇧 UK proxy for GBP pricing
            },
            "crawlerType": "playwright:chrome",
            "sameDomain": True,
            "useSitemaps": True,
            "maxPages": 30000,
            "maxDepth": 7,
            "maxResultRecords": max_results,
            "requestDelayMs": 1000,
            "maxConcurrency": 1,
            "requestTimeoutSecs": 120,
            "scrapeProducts": True,
            "scrapeCollections": True,
            "scrapeVariants": True,
            "downloadFiles": False,
            "downloadCss": False,
            "downloadMedia": False,
            "saveMarkdown": True,
            "saveHtml": True,
            "saveScreenshots": False,
            "excludeUrlGlobs": [
                "**/cart",
                "**/checkout",
                "**/customer",
                "**/account",
                "**/privacy",
                "**/terms",
                "**/media",
                "**/static",
                "**/search",
                "**/blog"
            ]
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            run_id = data.get('data', {}).get('id')

            logger.info(f"✅ Apify scraper started successfully: {run_id}")
            logger.info(f"🇬🇧 Using UK residential proxy for GBP pricing and UK-specific content")
            return run_id

        except Exception as e:
            logger.error(f"Error starting Apify scraper: {str(e)}")
            raise

    def check_status(self, run_id):
        """
        Check the status of an Apify run
        Returns: status string (RUNNING, SUCCEEDED, FAILED, etc.)
        """
        url = f"{self.base_url}/actor-runs/{run_id}"

        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            status = data.get('data', {}).get('status')

            return status

        except Exception as e:
            logger.error(f"Error checking Apify status: {str(e)}")
            return None

    def wait_for_completion(self, run_id, timeout=600, poll_interval=30):
        """
        Wait for Apify run to complete
        Returns: True if succeeded, False otherwise
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.check_status(run_id)

            if status == "SUCCEEDED":
                logger.info(f"Apify run {run_id} succeeded")
                return True
            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                logger.error(f"Apify run {run_id} failed with status: {status}")
                return False

            logger.info(f"Apify run {run_id} status: {status}, waiting...")
            time.sleep(poll_interval)

        logger.error(f"Apify run {run_id} timed out after {timeout}s")
        return False

    def get_last_run(self):
        """
        Get the last run of the Apify actor
        Returns: run_id and status
        """
        url = f"{self.base_url}/acts/{self.actor_id}/runs/last"

        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            run_data = data.get('data', {})
            run_id = run_data.get('id')
            status = run_data.get('status')

            logger.info(f"Last Apify run: {run_id}, status: {status}")
            return run_id, status

        except Exception as e:
            logger.error(f"Error getting last run: {str(e)}")
            return None, None

    def get_scraped_data(self, run_id, limit=200):
        """
        Fetch the scraped data from an Apify run
        Returns: list of product dictionaries
        """
        url = f"{self.base_url}/actor-runs/{run_id}/dataset/items"

        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        params = {
            "limit": limit,
            "format": "json"
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
            response.raise_for_status()

            products = response.json()
            logger.info(f"Fetched {len(products)} products from Apify")

            return products

        except Exception as e:
            logger.error(f"Error fetching scraped data: {str(e)}")
            return []

    def get_last_run_data(self, limit=200):
        """
        Get data from the last run directly
        Returns: list of product dictionaries
        """
        run_id, status = self.get_last_run()

        if not run_id:
            logger.error("Could not get last run ID")
            return []

        if status != "SUCCEEDED":
            logger.warning(f"Last run status is {status}, not SUCCEEDED")

        return self.get_scraped_data(run_id, limit)
