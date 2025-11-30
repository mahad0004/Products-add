# Shopify Option Names - Working Solution

## The Problem

Apify's `autofacts~shopify` actor doesn't extract option names from Shopify stores by default. It only gets option VALUES, resulting in generic "Option 1", "Option 2", "Option 3" labels.

## The Root Cause

Every Shopify product page has embedded JSON with FULL product data including option names:

```html
<script type="application/json" data-product-json>
{
  "title": "Test Product",
  "options": [
    {"name": "Size", "values": ["S", "M", "L"]},
    {"name": "Color", "values": ["Red", "Blue", "Green"]}
  ],
  "variants": [...]
}
</script>
```

The Apify scraper ISN'T extracting this JSON - it's scraping other parts of the page.

## The Solution

### Option 1: Use Shopify's Direct JSON API (RECOMMENDED)

Instead of scraping HTML, access Shopify's public JSON endpoint directly:

**Any Shopify product URL can be accessed as JSON:**
- HTML: `https://store.com/products/example-product`
- JSON: `https://store.com/products/example-product.json`

**Collection products:**
- JSON: `https://store.com/collections/all/products.json`

This JSON includes EVERYTHING including option names!

### Option 2: Custom Page Function in Apify

Add this custom JavaScript to extract the embedded product JSON:

```javascript
async function pageFunction(context) {
    const { page } = context;

    // Extract Shopify's embedded product JSON
    const productData = await page.evaluate(() => {
        // Method 1: Look for script tag with data-product-json
        let scriptTag = document.querySelector('script[data-product-json]');
        if (scriptTag) {
            try {
                return JSON.parse(scriptTag.textContent);
            } catch (e) {}
        }

        // Method 2: Look for any script containing product JSON
        const scripts = document.querySelectorAll('script[type="application/json"]');
        for (const script of scripts) {
            try {
                const data = JSON.parse(script.textContent);
                if (data.title && data.options && data.variants) {
                    return data;
                }
            } catch (e) {}
        }

        // Method 3: Check window.ShopifyAnalytics or meta tags
        if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta && window.ShopifyAnalytics.meta.product) {
            return window.ShopifyAnalytics.meta.product;
        }

        return null;
    });

    if (productData && productData.options) {
        return {
            ...context.request.userData,
            shopifyProduct: productData,
            options: productData.options,
            variants: productData.variants
        };
    }

    return context.request.userData;
}
```

### Option 3: Post-Processing Script

Create a Python script that fetches `.json` versions of product URLs after Apify scrapes:

```python
import requests

def enrich_with_shopify_json(product_url):
    """Fetch full product data from Shopify JSON API"""
    if not product_url.endswith('.json'):
        # Convert product URL to JSON endpoint
        product_url = product_url.rstrip('/') + '.json'

    response = requests.get(product_url)
    if response.status_code == 200:
        data = response.json()
        product = data.get('product', {})
        return {
            'options': product.get('options', []),
            'variants': product.get('variants', []),
            'title': product.get('title'),
            # ... full product data
        }
    return None
```

## Implementation Plan

### Immediate Fix (Quick & Reliable)

**Add a post-scrape enrichment step:**

1. After Apify returns product URLs
2. For each URL, fetch `{url}.json`
3. Extract `product.options` from JSON response
4. Merge with scraped data before saving to database

This is:
- ✅ Reliable (uses official Shopify API)
- ✅ Fast (direct HTTP request)
- ✅ No changes to Apify configuration needed
- ✅ Gets 100% accurate option names

### Code Changes Required

**File: `services/apify_service.py`**

Add new method:
```python
def enrich_product_with_json(self, product_url):
    """Fetch full product JSON from Shopify"""
    import requests

    if '/products/' not in product_url:
        return None

    json_url = product_url.rstrip('/') + '.json'

    try:
        response = requests.get(json_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('product', {})
    except:
        pass

    return None
```

**File: `app.py` (in scrape job processing)**

After getting products from Apify:
```python
for product in products:
    # Get product URL from scraped data
    product_url = product.get('url') or product.get('_original', {}).get('url')

    if product_url:
        # Fetch full JSON data
        shopify_data = apify_service.enrich_product_with_json(product_url)

        if shopify_data and 'options' in shopify_data:
            # Merge options into product data
            product['options'] = shopify_data['options']
            logger.info(f"✅ Enriched '{product.get('title')}' with {len(shopify_data['options'])} option names")

    # Continue with normal processing
    mapped = mapper.map_to_shopify(product)
    db_service.save_product(job_id, mapped)
```

## Expected Results

After implementation:
- ✅ Option names like "Size", "Color", "Material" extracted correctly
- ✅ Database populated with `option1_name`, `option2_name`, `option3_name`
- ✅ Shopify products show proper variant selector labels
- ✅ No more "Option 1", "Option 2", "Option 3"

## Testing

```bash
# Test fetching Shopify JSON directly
curl https://www.firstmats.co.uk/products/example-product.json | jq '.product.options'

# Should return:
[
  {"name": "Size", "position": 1, "values": [...]},
  {"name": "Color", "position": 2, "values": [...]}
]
```
