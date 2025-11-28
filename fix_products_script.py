"""
Simple script to fix 1000 products in Shopify
Removes brand names and contact information from titles and descriptions
"""

import os
import time
from dotenv import load_dotenv
from services.shopify_service import ShopifyService
from services.openai_service import OpenAIService

# Load environment variables
load_dotenv()

# Initialize services
shopify_service = ShopifyService(
    shop_url=os.getenv('SHOPIFY_SHOP_URL', '').strip(),
    access_token=os.getenv('SHOPIFY_ACCESS_TOKEN', '').strip()
)
openai_service = OpenAIService(os.getenv('OPENAI_API_KEY', '').strip())

def main():
    """Fix 1000 products by removing brand names and contact info"""
    product_limit = 1000

    print(f"\n{'='*80}")
    print(f"🔧 FIXING {product_limit} SHOPIFY PRODUCTS")
    print(f"{'='*80}\n")

    # Step 1: Fetch products from Shopify
    print(f"📦 Fetching {product_limit} products from Shopify...")
    all_products = []
    remaining = product_limit
    since_id = None

    while remaining > 0:
        batch_size = min(remaining, 250)
        print(f"   Fetching batch of {batch_size} products (since_id={since_id})...")

        products_batch = shopify_service.get_products(limit=batch_size, since_id=since_id)
        time.sleep(0.6)  # Shopify rate limit

        if not products_batch:
            print(f"   No more products available. Total fetched: {len(all_products)}")
            break

        all_products.extend(products_batch)
        remaining -= len(products_batch)

        # Update since_id for next batch
        if products_batch:
            since_id = products_batch[-1]['id']

        print(f"   ✅ Fetched {len(all_products)}/{product_limit} products")

        # If we got less than batch_size, we've reached the end
        if len(products_batch) < batch_size:
            break

    print(f"\n✅ Total products fetched: {len(all_products)}\n")

    if not all_products:
        print("❌ No products found. Exiting.")
        return

    # Step 2: Process each product
    print(f"{'='*80}")
    print(f"🔄 PROCESSING {len(all_products)} PRODUCTS")
    print(f"{'='*80}\n")

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for idx, shopify_product in enumerate(all_products, 1):
        try:
            product_id = shopify_product['id']
            current_title = shopify_product.get('title', '')
            current_body_html = shopify_product.get('body_html', '')

            print(f"\n[{idx}/{len(all_products)}] Processing: {current_title[:80]}")

            # Prepare data for OpenAI
            product_data = {
                'title': current_title,
                'description': current_body_html,
                'body_html': current_body_html,
                'price': '0.00',
                'product_type': shopify_product.get('product_type', ''),
                'vendor': shopify_product.get('vendor', '')
            }

            # Re-process through OpenAI
            print(f"   🤖 OpenAI: Cleaning product content...")
            enhanced_product = openai_service.enhance_product_description(product_data)
            time.sleep(0.5)  # OpenAI rate limit

            # Extract cleaned fields
            cleaned_title = enhanced_product.get('title', current_title)
            cleaned_body_html = enhanced_product.get('body_html', current_body_html)

            # Check if anything actually changed
            title_changed = cleaned_title != current_title
            body_changed = cleaned_body_html != current_body_html

            if not title_changed and not body_changed:
                print(f"   ⏭️  No changes needed - skipping")
                skipped_count += 1
                continue

            # Prepare update payload
            update_data = {}
            if title_changed:
                update_data['title'] = cleaned_title
                print(f"   📝 Title changed:")
                print(f"      Old: {current_title[:60]}...")
                print(f"      New: {cleaned_title[:60]}...")

            if body_changed:
                print(f"   📄 Description changed: {len(current_body_html)} -> {len(cleaned_body_html)} chars")

            # Update product in Shopify
            print(f"   🛍️  Shopify: Updating product...")
            updated = shopify_service.update_product(product_id, update_data)
            time.sleep(0.6)  # Shopify rate limit

            if updated:
                updated_count += 1
                print(f"   ✅ Product updated successfully!")
                print(f"   📊 Progress: {updated_count} updated, {skipped_count} skipped, {error_count} errors")
            else:
                error_count += 1
                print(f"   ❌ Failed to update product")

        except KeyboardInterrupt:
            print(f"\n\n⚠️  Operation cancelled by user")
            print(f"📊 Final Stats: {updated_count} updated, {skipped_count} skipped, {error_count} errors")
            return

        except Exception as e:
            error_count += 1
            print(f"   ❌ Error: {str(e)}")
            continue

    # Summary
    print(f"\n{'='*80}")
    print(f"✅ OPERATION COMPLETED")
    print(f"{'='*80}")
    print(f"Total processed:  {len(all_products)}")
    print(f"✅ Updated:       {updated_count}")
    print(f"⏭️  Skipped:       {skipped_count}")
    print(f"❌ Errors:        {error_count}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
