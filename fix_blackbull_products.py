"""
Script to find and fix ALL products containing "BLACK BULL" in Shopify
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
    """Find and fix all BLACK BULL products"""
    print(f"\n{'='*80}")
    print(f"🔍 SEARCHING FOR BLACK BULL PRODUCTS IN SHOPIFY")
    print(f"{'='*80}\n")

    # Step 1: Fetch ALL products from Shopify
    print(f"📦 Fetching ALL products from Shopify...")
    all_products = []
    since_id = None
    page_count = 0

    while True:
        page_count += 1
        print(f"   Fetching page {page_count} (since_id={since_id})...")

        products_batch = shopify_service.get_products(limit=250, since_id=since_id)
        time.sleep(0.6)  # Shopify rate limit

        if not products_batch:
            print(f"   No more products. Total fetched: {len(all_products)}")
            break

        all_products.extend(products_batch)

        # Update since_id for next batch
        since_id = products_batch[-1]['id']
        print(f"   ✅ Total fetched: {len(all_products)} products")

        # If we got less than 250, we've reached the end
        if len(products_batch) < 250:
            break

    print(f"\n✅ Total products fetched: {len(all_products)}\n")

    if not all_products:
        print("❌ No products found in Shopify. Exiting.")
        return

    # Step 2: Filter for BLACK BULL products
    print(f"{'='*80}")
    print(f"🔍 FILTERING FOR BLACK BULL PRODUCTS")
    print(f"{'='*80}\n")

    blackbull_products = []
    for product in all_products:
        title = product.get('title', '').lower()
        body_html = product.get('body_html', '').lower()

        if 'black bull' in title or 'black bull' in body_html:
            blackbull_products.append(product)
            print(f"   ✅ Found: {product.get('title', 'Untitled')[:80]}")

    print(f"\n{'='*80}")
    print(f"📊 FOUND {len(blackbull_products)} BLACK BULL PRODUCTS")
    print(f"{'='*80}\n")

    if not blackbull_products:
        print("✅ No BLACK BULL products found. All clean!")
        return

    # Step 3: Process each BLACK BULL product
    print(f"{'='*80}")
    print(f"🔄 CLEANING {len(blackbull_products)} BLACK BULL PRODUCTS")
    print(f"{'='*80}\n")

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for idx, shopify_product in enumerate(blackbull_products, 1):
        try:
            product_id = shopify_product['id']
            current_title = shopify_product.get('title', '')
            current_body_html = shopify_product.get('body_html', '')

            print(f"\n[{idx}/{len(blackbull_products)}] Processing: {current_title[:80]}")

            # Prepare data for OpenAI
            product_data = {
                'title': current_title,
                'description': current_body_html,
                'body_html': current_body_html,
                'price': '0.00',
                'product_type': shopify_product.get('product_type', ''),
                'vendor': shopify_product.get('vendor', '')
            }

            # Re-process through OpenAI to remove BLACK BULL
            print(f"   🤖 OpenAI: Removing BLACK BULL and cleaning content...")
            enhanced_product = openai_service.enhance_product_description(product_data)
            time.sleep(0.5)  # OpenAI rate limit

            # Extract cleaned fields
            cleaned_title = enhanced_product.get('title', current_title)
            cleaned_body_html = enhanced_product.get('body_html', current_body_html)

            # Check if anything actually changed
            title_changed = cleaned_title != current_title
            body_changed = cleaned_body_html != current_body_html

            if not title_changed and not body_changed:
                print(f"   ⏭️  No changes detected (OpenAI may have failed) - skipping")
                skipped_count += 1
                continue

            # IMPORTANT: Always include BOTH title AND body_html to avoid Shopify API errors
            update_data = {
                'title': cleaned_title,
                'body_html': cleaned_body_html
            }

            # Log changes
            if title_changed:
                print(f"   📝 Title changed:")
                print(f"      Old: {current_title[:60]}...")
                print(f"      New: {cleaned_title[:60]}...")
            else:
                print(f"   ℹ️  Title unchanged (keeping original)")

            if body_changed:
                print(f"   📄 Description changed: {len(current_body_html)} -> {len(cleaned_body_html)} chars")
            else:
                print(f"   ℹ️  Description unchanged (keeping original)")

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
    print(f"Total BLACK BULL products found:  {len(blackbull_products)}")
    print(f"✅ Updated:                        {updated_count}")
    print(f"⏭️  Skipped:                        {skipped_count}")
    print(f"❌ Errors:                         {error_count}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
