"""
Script to find and fix products with contact info or brand names in Shopify.
- Removes brand names from titles.
- Removes emails and phone numbers from descriptions.
"""

import os
import re
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

def has_contact_info(text):
    """Check for email or phone numbers in text."""
    # Check for email
    if '@' in text:
        return True
    # Check for phone numbers (basic regex)
    if re.search(r'(\d{3}[-\.\s]??\d{3}[-\.\s]??\d{4}|\(\d{3}\)\s*\d{3}[-\.\s]??\d{4}|\d{10,})', text):
        return True
    return False

def main():
    """Find and fix products with contact info or brand names."""
    print(f"\n{'='*80}")
    print(f"\uD83D\uDD0D SEARCHING FOR PRODUCTS WITH CONTACT INFO OR BRAND NAMES IN SHOPIFY")
    print(f"{'='*80}\n")

    # Step 1: Fetch ALL products from Shopify
    print(f"\U0001F4E6 Fetching ALL products from Shopify...")
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
        print(f"   \u2705 Total fetched: {len(all_products)} products")

        # If we got less than 250, we've reached the end
        if len(products_batch) < 250:
            break

    print(f"\n\u2705 Total products fetched: {len(all_products)}\n")

    if not all_products:
        print("\u274C No products found in Shopify. Exiting.")
        return

    # Step 2: Filter for products with issues
    print(f"{'='*80}")
    print(f"\uD83D\uDD0D FILTERING FOR PRODUCTS WITH CONTACT INFO OR BRAND NAMES")
    print(f"{'='*80}\n")

    products_to_fix = []
    for product in all_products:
        title = product.get('title', '')
        body_html = product.get('body_html', '')
        vendor = product.get('vendor', '')

        reason = ''
        # Check for brand name in title
        if vendor and vendor.lower() in title.lower():
            reason = f"Brand name '{vendor}' in title"
        # Check for contact info in description
        elif has_contact_info(body_html):
            reason = "Contact info in description"

        if reason:
            products_to_fix.append(product)
            print(f"   \u2705 Found: {product.get('title', 'Untitled')[:80]} (Reason: {reason})")

    print(f"\n{'='*80}")
    print(f"\U0001F4CA FOUND {len(products_to_fix)} PRODUCTS TO FIX")
    print(f"{'='*80}\n")

    if not products_to_fix:
        print("\u2705 No products with contact info or brand names found. All clean!")
        return

    # Step 3: Process each product to be fixed
    print(f"{'='*80}")
    print(f"\U0001F504 CLEANING {len(products_to_fix)} PRODUCTS")
    print(f"{'='*80}\n")

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for idx, shopify_product in enumerate(products_to_fix, 1):
        try:
            product_id = shopify_product['id']
            current_title = shopify_product.get('title', '')
            current_body_html = shopify_product.get('body_html', '')

            print(f"\n[{idx}/{len(products_to_fix)}] Processing: {current_title[:80]}")

            # Prepare data for OpenAI
            product_data = {
                'title': current_title,
                'description': current_body_html,
                'body_html': current_body_html,
                'price': '0.00',
                'product_type': shopify_product.get('product_type', ''),
                'vendor': shopify_product.get('vendor', '')
            }

            # Re-process through OpenAI to clean the content
            print(f"   \U0001F916 OpenAI: Removing brand names/contact info and cleaning content...")
            enhanced_product = openai_service.enhance_product_description(product_data)
            time.sleep(0.5)  # OpenAI rate limit

            # Extract cleaned fields
            cleaned_title = enhanced_product.get('title', current_title)
            cleaned_body_html = enhanced_product.get('body_html', current_body_html)

            # Check if anything actually changed
            title_changed = cleaned_title != current_title
            body_changed = cleaned_body_html != current_body_html

            if not title_changed and not body_changed:
                print(f"   \u23ED\uFE0F  No changes detected (OpenAI may have failed) - skipping")
                skipped_count += 1
                continue

            # IMPORTANT: Always include BOTH title AND body_html to avoid Shopify API errors
            update_data = {
                'title': cleaned_title,
                'body_html': cleaned_body_html
            }

            # Log changes
            if title_changed:
                print(f"   \U0001F4DD Title changed:")
                print(f"      Old: {current_title[:60]}...")
                print(f"      New: {cleaned_title[:60]}...")
            else:
                print(f"   \u2139\uFE0F  Title unchanged (keeping original)")

            if body_changed:
                print(f"   \U0001F4C4 Description changed: {len(current_body_html)} -> {len(cleaned_body_html)} chars")
            else:
                print(f"   \u2139\uFE0F  Description unchanged (keeping original)")

            # Update product in Shopify
            print(f"   \U0001F6CD\uFE0F  Shopify: Updating product...")
            updated = shopify_service.update_product(product_id, update_data)
            time.sleep(0.6)  # Shopify rate limit

            if updated:
                updated_count += 1
                print(f"   \u2705 Product updated successfully!")
                print(f"   \U0001F4CA Progress: {updated_count} updated, {skipped_count} skipped, {error_count} errors")
            else:
                error_count += 1
                print(f"   \u274C Failed to update product")

        except KeyboardInterrupt:
            print(f"\n\n\u26A0\uFE0F  Operation cancelled by user")
            print(f"\U0001F4CA Final Stats: {updated_count} updated, {skipped_count} skipped, {error_count} errors")
            return

        except Exception as e:
            error_count += 1
            print(f"   \u274C Error: {str(e)}")
            continue

    # Summary
    print(f"\n{'='*80}")
    print(f"\u2705 OPERATION COMPLETED")
    print(f"{'='*80}")
    print(f"Total products to fix found:  {len(products_to_fix)}")
    print(f"\u2705 Updated:                        {updated_count}")
    print(f"\u23ED\uFE0F  Skipped:                        {skipped_count}")
    print(f"\u274C Errors:                         {error_count}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
