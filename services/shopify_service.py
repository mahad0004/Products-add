"""
Shopify Service
Handles Shopify API interactions for product creation and management
"""

import requests
import time
import logging

logger = logging.getLogger(__name__)


class ShopifyService:
    """Service for interacting with Shopify Admin API"""

    def __init__(self, shop_url, access_token):
        if not shop_url:
            raise ValueError("SHOPIFY_SHOP_URL environment variable is required")
        if not access_token:
            raise ValueError("SHOPIFY_ACCESS_TOKEN environment variable is required")

        self.shop_url = shop_url.rstrip('/')
        self.access_token = access_token
        self.api_version = "2024-07"
        self.base_url = f"{self.shop_url}/admin/api/{self.api_version}"

    def _get_headers(self):
        """Get headers for Shopify API requests"""
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json"
        }

    def _rate_limit_wait(self):
        """Wait to respect Shopify rate limits (2 calls/second)"""
        time.sleep(0.5)

    def create_product(self, product_data):
        """
        Create a product in Shopify
        Returns: created product data or None
        """
        url = f"{self.base_url}/products.json"

        try:
            self._rate_limit_wait()

            # DEBUG: Log the product data being sent
            import json as json_module
            logger.info(f"🛍️ DEBUG: Sending product to Shopify:")
            logger.info(f"  Title: {product_data.get('title')}")
            logger.info(f"  Variants: {len(product_data.get('variants', []))}")
            logger.info(f"  Options: {product_data.get('options', [])}")
            if product_data.get('variants'):
                for idx, v in enumerate(product_data['variants'][:3], 1):
                    logger.info(f"    Variant {idx}: option1={v.get('option1')}, option2={v.get('option2')}, option3={v.get('option3')}, price={v.get('price')}")
            logger.info(f"  Full payload (first 1000 chars): {json_module.dumps({'product': product_data})[:1000]}")

            response = requests.post(
                url,
                json={"product": product_data},
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 201:
                # Status 201 = Product successfully created
                data = response.json()
                if 'product' in data:
                    logger.info(f"✅ Product created successfully: {data['product']['id']}")
                    return data['product']
                else:
                    logger.error(f"❌ Status 201 but unexpected response format: {response.text[:500]}")
                    return None

            elif response.status_code == 200:
                # Status 200 usually means the API call succeeded but didn't create a product
                # This happens when Shopify returns existing products instead of creating new one
                data = response.json()
                logger.error(f"🛍️ DEBUG: Status 200 response from Shopify (FULL): {response.text[:2000]}")
                if 'products' in data:
                    logger.error(f"❌ Product creation failed - Shopify returned existing products instead")
                    logger.error(f"   Attempted to create: {product_data.get('title', 'Unknown')}")
                    logger.error(f"   Shopify returned: {data['products'][0].get('title', 'Unknown') if data['products'] else 'No products'}")
                    logger.error(f"   This usually means validation failed or duplicate detected")
                    return None
                else:
                    logger.error(f"❌ Status 200 with unexpected format: {response.text[:500]}")
                    return None

            else:
                logger.error(f"❌ Error creating product: {response.status_code}")
                logger.error(f"   Response: {response.text[:500]}")
                return None

        except Exception as e:
            logger.error(f"Exception creating product: {str(e)}")
            return None

    def add_product_image(self, product_id, image_url):
        """
        Add an image to a Shopify product
        Supports both HTTP URLs and base64 data URLs
        Returns: True if successful, False otherwise
        """
        url = f"{self.base_url}/products/{product_id}/images.json"

        # Check if image_url is a base64 data URL
        if image_url.startswith('data:image/'):
            # Extract base64 data (remove "data:image/png;base64," prefix)
            try:
                # Split to get the base64 part
                parts = image_url.split(',', 1)
                if len(parts) == 2:
                    base64_data = parts[1]

                    # Use attachment field for base64
                    payload = {
                        "image": {
                            "attachment": base64_data
                        }
                    }
                    logger.info(f"Adding base64 image to product {product_id}")
                else:
                    logger.error("Invalid base64 data URL format")
                    return False
            except Exception as e:
                logger.error(f"Error parsing base64 data URL: {str(e)}")
                return False
        else:
            # Use src field for HTTP URLs
            payload = {
                "image": {
                    "src": image_url
                }
            }
            logger.info(f"Adding HTTP image to product {product_id}")

        try:
            self._rate_limit_wait()

            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code in [200, 201]:
                image_type = "base64 AI-generated" if image_url.startswith('data:image/') else "HTTP URL"
                logger.info(f"✅ Image added successfully to product {product_id} ({image_type})")
                return True
            else:
                image_type = "base64" if image_url.startswith('data:image/') else "HTTP URL"
                logger.error(f"❌ Error adding {image_type} image: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Exception adding image: {str(e)}")
            return False

    def add_metafields(self, product_id, metafields):
        """
        Add metafields to a Shopify product
        metafields: list of {namespace, key, type, value}
        """
        url = f"{self.base_url}/products/{product_id}/metafields.json"

        for metafield in metafields:
            try:
                self._rate_limit_wait()

                payload = {
                    "metafield": {
                        "namespace": metafield.get('namespace', 'custom'),
                        "key": metafield['key'],
                        "type": metafield.get('type', 'single_line_text_field'),
                        "value": metafield['value']
                    }
                }

                response = requests.post(
                    url,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=30
                )

                if response.status_code in [200, 201]:
                    logger.info(f"Metafield added: {metafield['key']}")
                else:
                    logger.error(f"Error adding metafield: {response.status_code} - {response.text}")

            except Exception as e:
                logger.error(f"Exception adding metafield: {str(e)}")
                continue

    def disable_inventory_tracking(self, inventory_item_id):
        """
        Disable inventory tracking for a variant
        """
        url = f"{self.base_url}/inventory_items/{inventory_item_id}.json"

        payload = {
            "inventory_item": {
                "id": inventory_item_id,
                "tracked": False
            }
        }

        try:
            self._rate_limit_wait()

            response = requests.put(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 200:
                logger.info(f"Inventory tracking disabled for item {inventory_item_id}")
                return True
            else:
                logger.error(f"Error disabling inventory: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Exception disabling inventory: {str(e)}")
            return False

    def get_product(self, product_id):
        """Get product details"""
        url = f"{self.base_url}/products/{product_id}.json"

        try:
            self._rate_limit_wait()

            response = requests.get(url, headers=self._get_headers(), timeout=30)

            if response.status_code == 200:
                return response.json()['product']
            else:
                return None

        except Exception as e:
            logger.error(f"Exception getting product: {str(e)}")
            return None

    def find_products_by_title(self, title):
        """
        Search for products by exact title match
        Returns: list of matching products or empty list
        """
        url = f"{self.base_url}/products.json"

        try:
            self._rate_limit_wait()

            # Search with title parameter
            response = requests.get(
                url,
                params={"title": title, "limit": 250},
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 200:
                products = response.json().get('products', [])
                # Filter for exact title match (case insensitive)
                matching_products = [p for p in products if p.get('title', '').lower() == title.lower()]
                logger.info(f"Found {len(matching_products)} product(s) with title: {title}")
                return matching_products
            else:
                logger.error(f"Error searching products: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            logger.error(f"Exception searching products: {str(e)}")
            return []

    def delete_product(self, product_id):
        """
        Delete a product from Shopify
        Returns: True if successful, False otherwise
        """
        url = f"{self.base_url}/products/{product_id}.json"

        try:
            self._rate_limit_wait()

            response = requests.delete(url, headers=self._get_headers(), timeout=30)

            if response.status_code == 200:
                logger.info(f"Product {product_id} deleted successfully")
                return True
            else:
                logger.error(f"Error deleting product: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Exception deleting product: {str(e)}")
            return False

    def get_products(self, limit=250, since_id=None):
        """
        Get products from Shopify
        Args:
            limit: Number of products to retrieve (max 250 per request)
            since_id: Get products after this ID (for pagination)
        Returns: list of products or empty list
        """
        url = f"{self.base_url}/products.json"

        params = {"limit": min(limit, 250)}
        if since_id:
            params["since_id"] = since_id

        try:
            self._rate_limit_wait()

            response = requests.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 200:
                products = response.json().get('products', [])
                logger.info(f"Retrieved {len(products)} products from Shopify")
                return products
            else:
                logger.error(f"Error getting products: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            logger.error(f"Exception getting products: {str(e)}")
            return []

    def update_product(self, product_id, product_data):
        """
        Update a product in Shopify
        Args:
            product_id: Shopify product ID
            product_data: Product data to update (only include fields you want to change)
        Returns: updated product data or None
        """
        url = f"{self.base_url}/products/{product_id}.json"

        try:
            self._rate_limit_wait()

            response = requests.put(
                url,
                json={"product": product_data},
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                if 'product' in data:
                    logger.info(f"Product {product_id} updated successfully")
                    return data['product']
                else:
                    logger.error(f"Status 200 but unexpected response format: {response.text[:500]}")
                    return None
            else:
                logger.error(f"Error updating product: {response.status_code}")
                logger.error(f"Response: {response.text[:500]}")
                return None

        except Exception as e:
            logger.error(f"Exception updating product: {str(e)}")
            return None
