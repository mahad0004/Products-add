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
        # Using hoppr~shopify-scraper for full product schema extraction including option names
        self.actor_id = "hoppr~shopify-scraper"

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
        # hoppr~shopify-scraper uses Shopify's native JSON API for complete product data
        payload = {
            "startUrls": [{"url": shopify_url}],
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
                "apifyProxyCountry": "GB"  # 🇬🇧 UK proxy for GBP pricing
            },
            "maxRequestsPerCrawl": max_results,
            "maxConcurrency": 5,
            "maxRequestRetries": 3,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
                "apifyProxyCountry": "GB"
            },
            # Extract full product data including option names from Shopify JSON API
            "scrapeProductDetails": True,
            "scrapeVariants": True,
            "scrapeImages": True,
            "includeProductJson": True  # 🎯 This ensures we get the full product.options array
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            run_id = data.get('data', {}).get('id')

            logger.info(f"✅ Apify scraper started successfully: {run_id}")
            logger.info(f"🔧 Using hoppr~shopify-scraper for full product schema extraction")
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

            # DEBUG: Log detailed run information
            logger.info(f"🔍 DEBUG: Last run full data:")
            logger.info(f"  Run ID: {run_id}")
            logger.info(f"  Status: {status}")
            logger.info(f"  Started at: {run_data.get('startedAt')}")
            logger.info(f"  Finished at: {run_data.get('finishedAt')}")
            logger.info(f"  Default dataset ID: {run_data.get('defaultDatasetId')}")

            # Check stats
            stats = run_data.get('stats', {})
            logger.info(f"  Stats: {stats}")

            # Check output
            output = run_data.get('output', {})
            logger.info(f"  Output: {output}")

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
            logger.info(f"🔍 DEBUG: Fetching data from Apify run {run_id}")
            logger.info(f"🔍 DEBUG: URL: {url}")
            logger.info(f"🔍 DEBUG: Params: {params}")

            response = requests.get(url, headers=headers, params=params, timeout=60)

            logger.info(f"🔍 DEBUG: Response status: {response.status_code}")
            logger.info(f"🔍 DEBUG: Response headers: {dict(response.headers)}")

            response.raise_for_status()

            products = response.json()

            # DEBUG: Log detailed information about the response
            logger.info(f"🔍 DEBUG: Response type: {type(products)}")
            logger.info(f"🔍 DEBUG: Response length: {len(products) if isinstance(products, list) else 'N/A'}")

            if isinstance(products, list) and len(products) > 0:
                logger.info(f"🔍 DEBUG: First product keys: {list(products[0].keys())[:10]}")
                logger.info(f"🔍 DEBUG: First product sample: {str(products[0])[:500]}")
            elif isinstance(products, dict):
                logger.info(f"🔍 DEBUG: Response is dict with keys: {list(products.keys())}")
                logger.info(f"🔍 DEBUG: Full response: {str(products)[:1000]}")
            else:
                logger.info(f"🔍 DEBUG: Raw response text (first 2000 chars): {response.text[:2000]}")

            logger.info(f"Fetched {len(products)} products from Apify")

            return products

        except Exception as e:
            logger.error(f"Error fetching scraped data: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def check_dataset(self, dataset_id):
        """
        Check dataset information and item count
        Returns: dict with dataset info
        """
        url = f"{self.base_url}/datasets/{dataset_id}"

        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            dataset_info = data.get('data', {})

            logger.info(f"🔍 DEBUG: Dataset {dataset_id} info:")
            logger.info(f"  Item count: {dataset_info.get('itemCount')}")
            logger.info(f"  Clean item count: {dataset_info.get('cleanItemCount')}")
            logger.info(f"  Created at: {dataset_info.get('createdAt')}")
            logger.info(f"  Modified at: {dataset_info.get('modifiedAt')}")

            return dataset_info

        except Exception as e:
            logger.error(f"Error checking dataset: {str(e)}")
            return {}

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

        # Get the run details to find the dataset ID
        url = f"{self.base_url}/actor-runs/{run_id}"
        headers = {"Authorization": f"Bearer {self.api_token}"}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            run_data = response.json().get('data', {})
            dataset_id = run_data.get('defaultDatasetId')

            if dataset_id:
                logger.info(f"🔍 Checking dataset {dataset_id} for run {run_id}")
                self.check_dataset(dataset_id)
        except Exception as e:
            logger.warning(f"Could not check dataset info: {str(e)}")

        return self.get_scraped_data(run_id, limit)
