"""
Product Mapper
Maps scraped product data to Shopify format
This replicates the logic from Code in JavaScript6 node in N8N
"""

import re
import json
import logging

logger = logging.getLogger(__name__)


class ProductMapper:
    """Maps product data to Shopify format"""

    DEFAULT_PRICE = 99.00
    DEFAULT_CURRENCY = "GBP"

    def __init__(self):
        pass

    @staticmethod
    def slugify(text):
        """Convert text to URL-friendly slug"""
        if not text:
            return ""

        # Normalize and convert to lowercase
        text = str(text).lower()

        # Remove special characters
        text = re.sub(r'[^\w\s-]', '', text)

        # Replace spaces and multiple hyphens with single hyphen
        text = re.sub(r'[\s_-]+', '-', text)

        # Remove leading/trailing hyphens
        text = text.strip('-')

        return text[:200]

    def adjust_prices(self, products):
        """
        Adjust product prices: Divide by 100, then multiply by 2

        IMPORTANT: Apify scraper returns UK prices in PENCE (not pounds).
        PRIORITY: Use VAT-inclusive price (higher price when two prices exist)

        Process:
        1. Extract price - prioritize VAT-inclusive price (if two prices, use HIGHER)
        2. Divide by 100 to convert pence to pounds (1598 pence = £15.98)
        3. Multiply by 2 for markup

        Example: 1598 pence (incl VAT) → £15.98 → £31.96 (final price with 2x markup)
        """
        for product in products:
            try:
                # Handle variants
                if 'variants' in product and isinstance(product['variants'], list):
                    for variant in product['variants']:
                        if 'price' in variant:
                            if isinstance(variant['price'], dict) and 'current' in variant['price']:
                                price_in_pence = variant['price']['current']
                                # Convert pence to pounds, then multiply by 2 for markup
                                price_in_pounds = float(price_in_pence) / 100
                                variant['price']['current'] = price_in_pounds * 2
                            elif isinstance(variant['price'], (int, float)):
                                price_in_pence = variant['price']
                                # Convert pence to pounds, then multiply by 2 for markup
                                price_in_pounds = float(price_in_pence) / 100
                                variant['price'] = price_in_pounds * 2

                # Handle product-level price
                if 'price' in product:
                    if isinstance(product['price'], dict) and 'current' in product['price']:
                        price_in_pence = product['price']['current']
                        # Convert pence to pounds, then multiply by 2 for markup
                        price_in_pounds = float(price_in_pence) / 100
                        product['price']['current'] = price_in_pounds * 2
                    elif isinstance(product['price'], (int, float)):
                        price_in_pence = product['price']
                        # Convert pence to pounds, then multiply by 2 for markup
                        price_in_pounds = float(price_in_pence) / 100
                        product['price'] = price_in_pounds * 2

            except Exception as e:
                logger.error(f"Error adjusting prices: {str(e)}")
                continue

        return products

    def map_to_shopify(self, product):
        """
        Map scraped product data to Shopify format
        Replicates the Code in JavaScript6 node logic
        """
        # Extract title and handle
        title = str(product.get('title') or product.get('name') or 'Untitled Product')
        title = title.replace('\n', ' ').strip()

        handle = product.get('handle') or product.get('slug') or self.slugify(title)
        handle = self.slugify(handle)

        # Description
        body_html = str(product.get('body_html') or product.get('description_text') or product.get('description') or '').strip()

        # Product type
        product_type = product.get('product_type', '')
        if not product_type and product.get('categories'):
            categories = product['categories']
            if isinstance(categories, list) and categories:
                product_type = str(categories[0])
            elif isinstance(categories, str):
                product_type = categories.split(',')[0].strip()

        if not product_type:
            product_type = 'Products'

        # Tags
        tags = ''
        if product.get('tags'):
            if isinstance(product['tags'], list):
                tags = ', '.join(str(t) for t in product['tags'] if t)
            elif isinstance(product['tags'], str):
                tags = product['tags']

        # Build variants
        variants = self._build_variants(product)

        # Build options from variants
        options = self._build_options(product, variants)

        # Build metafields
        metafields = self._build_metafields(product)

        # Construct Shopify product
        shopify_product = {
            'title': title,
            'handle': handle,
            'body_html': body_html,
            'product_type': product_type,
            'tags': tags,
            'status': 'active',  # Always active
            'vendor': product.get('vendor') or product.get('brand') or 'Unknown',
            'options': options if options else [{'name': 'Title'}],
            'variants': variants,
        }

        # Add metafields if any
        if metafields:
            shopify_product['metafields'] = metafields

        # Store original data for reference
        shopify_product['_original'] = product
        shopify_product['collection_name'] = product.get('collection_name') or product.get('collection')
        shopify_product['collection_tag'] = product.get('collection_tag')

        return shopify_product

    def _extract_price(self, variant, parent_product):
        """
        Extract price from variant with fallbacks

        PRIORITY: Use include VAT price (higher price) when available
        If two prices exist, always use the HIGHER price (which is typically the VAT-inclusive price)
        """
        # Collect all possible price candidates with their sources
        price_candidates = []

        # Check variant prices
        if isinstance(variant.get('price'), dict):
            # If price is a dict, check for 'current', 'incl_vat', 'with_vat', etc.
            price_dict = variant.get('price')
            if price_dict.get('incl_vat') is not None:
                price_candidates.append(float(price_dict['incl_vat']))
            if price_dict.get('with_vat') is not None:
                price_candidates.append(float(price_dict['with_vat']))
            if price_dict.get('current') is not None:
                price_candidates.append(float(price_dict['current']))

        # Check other variant price fields
        if variant.get('price_incl_vat') is not None:
            try:
                price_candidates.append(float(variant['price_incl_vat']))
            except (ValueError, TypeError):
                pass

        if variant.get('price_with_vat') is not None:
            try:
                price_candidates.append(float(variant['price_with_vat']))
            except (ValueError, TypeError):
                pass

        if variant.get('price_current') is not None:
            try:
                price_candidates.append(float(variant['price_current']))
            except (ValueError, TypeError):
                pass

        if variant.get('current') is not None:
            try:
                price_candidates.append(float(variant['current']))
            except (ValueError, TypeError):
                pass

        if variant.get('price') is not None and not isinstance(variant.get('price'), dict):
            try:
                price_candidates.append(float(variant['price']))
            except (ValueError, TypeError):
                pass

        # Check parent product prices
        if isinstance(parent_product.get('price'), dict):
            price_dict = parent_product.get('price')
            if price_dict.get('incl_vat') is not None:
                price_candidates.append(float(price_dict['incl_vat']))
            if price_dict.get('with_vat') is not None:
                price_candidates.append(float(price_dict['with_vat']))
            if price_dict.get('current') is not None:
                price_candidates.append(float(price_dict['current']))

        if parent_product.get('price_incl_vat') is not None:
            try:
                price_candidates.append(float(parent_product['price_incl_vat']))
            except (ValueError, TypeError):
                pass

        if parent_product.get('price_with_vat') is not None:
            try:
                price_candidates.append(float(parent_product['price_with_vat']))
            except (ValueError, TypeError):
                pass

        if parent_product.get('price_current') is not None:
            try:
                price_candidates.append(float(parent_product['price_current']))
            except (ValueError, TypeError):
                pass

        if parent_product.get('price') is not None and not isinstance(parent_product.get('price'), dict):
            try:
                price_candidates.append(float(parent_product['price']))
            except (ValueError, TypeError):
                pass

        if parent_product.get('current') is not None:
            try:
                price_candidates.append(float(parent_product['current']))
            except (ValueError, TypeError):
                pass

        # Filter valid prices (>= 0)
        valid_prices = [p for p in price_candidates if p >= 0]

        if valid_prices:
            # Use the HIGHER price (which is typically the VAT-inclusive price)
            highest_price = max(valid_prices)
            return highest_price

        return self.DEFAULT_PRICE

    def _build_variants(self, product):
        """Build Shopify variants from product data"""
        incoming_variants = product.get('variants', [])

        if not isinstance(incoming_variants, list) or not incoming_variants:
            # No variants, create default variant
            price = self._extract_price({}, product)

            return [{
                'price': f"{price:.2f}",
                'title': 'Default Title',
                'requires_shipping': True,
                'taxable': True,
                'inventory_management': None,
                'inventory_policy': 'continue'
            }]

        # Build variants from incoming data
        variants = []

        for v in incoming_variants:
            # FILTER OUT PLACEHOLDER VARIANTS
            # Skip variants that are clearly placeholders from the source
            variant_title = str(v.get('title', '')).lower()
            variant_option1 = str(v.get('option1', '')).lower() if v.get('option1') else ''

            # Check for placeholder text
            placeholder_keywords = [
                'please select', 'select option', 'choose', 'select size',
                'select color', 'select variant', 'default title'
            ]

            is_placeholder = any(keyword in variant_title for keyword in placeholder_keywords) or \
                           any(keyword in variant_option1 for keyword in placeholder_keywords)

            if is_placeholder:
                logger.info(f"⏭️  Skipping placeholder variant: {v.get('title')} (option1: {v.get('option1')})")
                continue

            price = self._extract_price(v, product)

            # Skip zero-price variants - NO zero-price products allowed
            if price <= 0.01:
                logger.warning(f"⏭️  SKIPPING VARIANT: Zero/missing price in scraped data")
                logger.warning(f"     Variant: {v.get('title')} (Price: £{price})")
                logger.warning(f"     → Check Apify scraper or source Shopify store")
                continue

            # Compare at price
            compare_at_price = None
            previous_candidates = [
                v.get('price', {}).get('previous') if isinstance(v.get('price'), dict) else None,
                v.get('previous'),
                product.get('previous')
            ]

            for prev in previous_candidates:
                if prev is not None:
                    try:
                        prev_price = float(prev)
                        if prev_price > price:
                            compare_at_price = f"{prev_price:.2f}"
                            break
                    except (ValueError, TypeError):
                        continue

            # Extract option values
            option_values = []
            if isinstance(v.get('options'), list):
                option_values = [str(opt) for opt in v['options']]
            elif isinstance(v.get('option_values'), list):
                option_values = [str(opt) for opt in v['option_values']]
            elif isinstance(v.get('option'), str):
                option_values = [str(v['option'])]

            variant = {
                'price': f"{price:.2f}",
                'requires_shipping': True,
                'taxable': True,
                'inventory_management': None,
                'inventory_policy': 'continue',
                'fulfillment_service': 'manual'
            }

            # Add compare at price if exists
            if compare_at_price:
                variant['compare_at_price'] = compare_at_price

            # Add SKU and barcode if available
            if v.get('sku'):
                variant['sku'] = str(v['sku'])
            if v.get('barcode'):
                variant['barcode'] = str(v['barcode'])

            # Add option values
            for i, value in enumerate(option_values[:3], 1):
                variant[f'option{i}'] = value

            # Set title first
            if v.get('title'):
                variant['title'] = str(v['title'])
            elif option_values:
                variant['title'] = ' / '.join(option_values)
            else:
                # Use variant index to make unique title
                variant['title'] = f'Variant {len(variants) + 1}'

            # CRITICAL FIX: Parse title into option values if no options were found
            # This handles cases where Apify provides variant titles like "Yellow & Black / 3000mm"
            # but doesn't provide structured option1, option2, option3 values
            if 'option1' not in variant and variant.get('title'):
                title_parts = variant['title'].split('/')
                title_parts = [part.strip() for part in title_parts if part.strip()]

                if title_parts:
                    # Set option1, option2, option3 from parsed title parts
                    for i, part in enumerate(title_parts[:3], 1):
                        variant[f'option{i}'] = part
                else:
                    # Fallback: use full title as option1
                    variant['option1'] = variant['title']

            # Final fallback: only set option1 if we have actual option values
            # Don't set option1 for single-variant products to avoid "Option 1: Default" display
            if 'option1' not in variant:
                # If title suggests this is not a default variant, use title as option1
                if variant['title'] and variant['title'] not in ['Default Title', 'Default', f'Variant {len(variants) + 1}']:
                    variant['option1'] = variant['title']
                # Otherwise, leave option1 unset for single-variant products

            variants.append(variant)

        # Ensure we have at least one variant
        # If all variants were filtered out (all were placeholders), create a default variant
        if not variants:
            logger.warning(f"⚠️  All variants were placeholders/invalid - creating default variant")
            price = self._extract_price({}, product)

            variants = [{
                'price': f"{price:.2f}",
                'title': 'Default Title',
                'requires_shipping': True,
                'taxable': True,
                'inventory_management': None,
                'inventory_policy': 'continue'
            }]

        return variants

    def _build_options(self, product, variants):
        """Build Shopify options from product and variants"""
        options_data = product.get('options', [])

        option_map = {}

        # Try to extract from _original.source first (full Shopify JSON)
        if not options_data and product.get('_original', {}).get('source', {}).get('options'):
            logger.info("🔍 Trying to extract option names from _original.source")
            source_options = product.get('_original', {}).get('source', {}).get('options', [])
            if isinstance(source_options, list):
                options_data = source_options

        # Parse from product options
        if isinstance(options_data, list):
            for opt in options_data:
                if isinstance(opt, dict):
                    name = opt.get('name') or opt.get('type') or opt.get('id') or 'Option'
                    values = []

                    if isinstance(opt.get('values'), list):
                        values = [str(v) for v in opt['values']]
                    elif opt.get('value'):
                        values = [str(opt['value'])]

                    if name not in option_map:
                        option_map[name] = set(values)
                        logger.info(f"✅ Found option name: '{name}' with {len(values)} values")
                    else:
                        option_map[name].update(values)

        # If no options found, infer from variants
        if not option_map and variants:
            # Determine max option count
            max_options = 1

            for v in variants:
                for i in range(1, 4):
                    if v.get(f'option{i}'):
                        max_options = max(max_options, i)

            # Create option sets
            for i in range(1, max_options + 1):
                option_name = f'Option {i}'
                option_map[option_name] = set()

                for v in variants:
                    value = v.get(f'option{i}')
                    # Exclude default values - these are for single-variant products
                    if value and value not in ['Default', 'Default Title']:
                        option_map[option_name].add(value)

        # Build final options array
        if not option_map:
            return [{'name': 'Title'}]

        options = []
        for name, values in option_map.items():
            values_list = list(values) if values else ['Default']
            options.append({'name': name})

        return options if options else [{'name': 'Title'}]

    def _build_metafields(self, product):
        """Build metafields array"""
        metafields = []

        # Add SEO metafields
        if product.get('seo_title'):
            metafields.append({
                'namespace': 'seo',
                'key': 'title_tag',
                'type': 'single_line_text_field',
                'value': str(product['seo_title'])
            })

        if product.get('seo_description'):
            metafields.append({
                'namespace': 'seo',
                'key': 'description_tag',
                'type': 'multi_line_text_field',
                'value': str(product['seo_description'])
            })

        if product.get('image_prompt'):
            metafields.append({
                'namespace': 'aigen',
                'key': 'image_prompt',
                'type': 'multi_line_text_field',
                'value': str(product['image_prompt'])
            })

        # Parse additional metafields
        if product.get('metafields'):
            metafields_data = product['metafields']

            if isinstance(metafields_data, list):
                for mf in metafields_data:
                    normalized = self._normalize_metafield(mf)
                    if normalized:
                        metafields.append(normalized)
            elif isinstance(metafields_data, dict):
                normalized = self._normalize_metafield(metafields_data)
                if normalized:
                    metafields.append(normalized)

        # Deduplicate by namespace::key
        dedup_map = {}
        for mf in metafields:
            key = f"{mf['namespace']}::{mf['key']}"
            dedup_map[key] = mf

        return list(dedup_map.values())

    def _normalize_metafield(self, entry):
        """Normalize a metafield entry"""
        if not entry:
            return None

        if isinstance(entry, str):
            entry = entry.strip()
            if not entry:
                return None

            # Try parsing as JSON
            try:
                parsed = json.loads(entry)
                if isinstance(parsed, dict):
                    entry = parsed
            except:
                # Parse as pipe-delimited or key:value
                if '|' in entry:
                    parts = [p.strip() for p in entry.split('|')]
                    if len(parts) >= 2:
                        return {
                            'namespace': parts[0] or 'attributes',
                            'key': parts[1] or 'attr_1',
                            'type': parts[2] if len(parts) > 2 else 'single_line_text_field',
                            'value': parts[3] if len(parts) > 3 else (parts[2] if len(parts) > 2 else '')
                        }
                elif ':' in entry:
                    kv = entry.split(':', 1)
                    return {
                        'namespace': 'attributes',
                        'key': self.slugify(kv[0].strip())[:50] or 'attr_1',
                        'type': 'single_line_text_field',
                        'value': kv[1].strip() if len(kv) > 1 else ''
                    }

                return {
                    'namespace': 'attributes',
                    'key': 'attr_1',
                    'type': 'single_line_text_field',
                    'value': entry
                }

        if isinstance(entry, dict):
            namespace = entry.get('namespace') or entry.get('ns') or 'attributes'
            key = entry.get('key') or entry.get('k')
            field_type = entry.get('type') or entry.get('field_type') or 'single_line_text_field'

            value = entry.get('value')
            if value is None or value == '':
                value = entry.get('val')

            if not key or value is None:
                return None

            return {
                'namespace': str(namespace),
                'key': str(key),
                'type': str(field_type),
                'value': str(value) if value is not None else ''
            }

        return None

    def generate_image_prompt(self, product):
        """
        Generate AI image prompt based on product attributes
        Replicates Code13 logic
        """
        title = product.get('title', '').lower()
        tags = product.get('tags', '').lower()
        combined = f"{title} {tags}"

        # Detect materials
        material = 'generic material'
        if 'aluminium' in combined or 'aluminum' in combined:
            material = 'aluminium with brushed metal finish'
        elif 'grp' in combined or 'fiberglass' in combined:
            material = 'GRP (fiberglass reinforced plastic) with smooth gelcoat finish'
        elif 'vinyl' in combined:
            material = 'high-quality vinyl with weather-resistant coating'
        elif 'rubber' in combined:
            material = 'commercial-grade rubber with textured surface'

        # Determine environment
        environment = 'outdoor industrial setting'
        if 'indoor' in combined:
            environment = 'professional indoor warehouse environment'

        # Detect special features
        special_features = ''
        if 'high visibility yellow' in combined or 'hi-vis yellow' in combined:
            special_features = ', featuring prominent high-visibility yellow safety inserts'

        prompt = f"""realistic 45° product shot of {product.get('title', 'product')} ({material}) in its {environment},
realistic lifestyle background, natural soft lighting, high detail, no text or watermark,
professional product photography, clean composition, sharp focus{special_features},
remove any existing watermarks or text overlays"""

        return prompt.strip()
