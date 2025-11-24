"""
Database Models
SQLAlchemy models for storing scraped products
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()


class ScrapeJob(db.Model):
    """Tracks scraping jobs"""
    __tablename__ = 'scrape_jobs'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(100), unique=True, nullable=False)
    source_url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(50), default='pending')  # pending, running, completed, failed
    apify_run_id = db.Column(db.String(100))
    total_products = db.Column(db.Integer, default=0)
    products_processed = db.Column(db.Integer, default=0)
    products_pushed = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # Relationships
    products = db.relationship('Product', backref='scrape_job', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'source_url': self.source_url,
            'status': self.status,
            'total_products': self.total_products,
            'products_processed': self.products_processed,
            'products_pushed': self.products_pushed,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class Product(db.Model):
    """Stores scraped products before pushing to Shopify"""
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('scrape_jobs.id'), nullable=False)

    # Product details
    title = db.Column(db.String(500), nullable=False)
    handle = db.Column(db.String(500))
    body_html = db.Column(db.Text)
    product_type = db.Column(db.String(200))
    tags = db.Column(db.Text)
    vendor = db.Column(db.String(200))

    # SEO fields
    seo_title = db.Column(db.String(500))
    seo_description = db.Column(db.Text)

    # Status tracking
    status = db.Column(db.String(50), default='pending')  # pending, approved, rejected, pushed
    shopify_product_id = db.Column(db.String(100))

    # Original scraped data (JSON)
    original_data = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pushed_at = db.Column(db.DateTime)

    # Relationships
    variants = db.relationship('ProductVariant', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    images = db.relationship('ProductImage', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    metafields = db.relationship('ProductMetafield', backref='product', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'job_id': self.job_id,
            'title': self.title,
            'handle': self.handle,
            'body_html': self.body_html,
            'product_type': self.product_type,
            'tags': self.tags,
            'vendor': self.vendor,
            'seo_title': self.seo_title,
            'seo_description': self.seo_description,
            'status': self.status,
            'shopify_product_id': self.shopify_product_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'pushed_at': self.pushed_at.isoformat() if self.pushed_at else None
        }

        if include_relations:
            data['variants'] = [v.to_dict() for v in self.variants.all()]
            data['images'] = [i.to_dict() for i in self.images.all()]
            data['metafields'] = [m.to_dict() for m in self.metafields.all()]

        return data

    def to_shopify_format(self):
        """Convert to Shopify API format"""
        import logging
        logger = logging.getLogger(__name__)

        # Get all variants
        all_variants = [v.to_shopify_format() for v in self.variants.all()]

        logger.info(f"Product '{self.title}': Processing {len(all_variants)} total variants")

        # Remove duplicate variants (same option1, option2, option3)
        # Shopify will reject products with duplicate variants
        seen_variants = set()
        unique_variants = []
        duplicates_removed = 0

        for idx, variant in enumerate(all_variants, 1):
            # Create a tuple of option values for comparison
            variant_key = (
                variant.get('option1', 'Default'),
                variant.get('option2'),
                variant.get('option3')
            )

            if variant_key not in seen_variants:
                seen_variants.add(variant_key)
                unique_variants.append(variant)
                logger.info(f"  ✅ Variant {idx}: {variant.get('title')} (£{variant.get('price')}) - Options: {variant_key}")
            else:
                duplicates_removed += 1
                logger.warning(f"  ⚠️ Variant {idx}: {variant.get('title')} REMOVED (duplicate options: {variant_key})")

        if duplicates_removed > 0:
            logger.warning(f"⚠️ Removed {duplicates_removed} duplicate variant(s) from '{self.title}'")

        logger.info(f"✅ Final: {len(unique_variants)} unique variant(s) will be sent to Shopify")

        # If no variants or all were duplicates, ensure at least one variant
        if not unique_variants:
            logger.warning(f"⚠️ No unique variants found, creating default variant")
            unique_variants = [{
                'title': 'Default',
                'price': '0.00',
                'option1': 'Default',
                'requires_shipping': True,
                'taxable': True,
                'inventory_management': None,
                'inventory_policy': 'continue',
                'fulfillment_service': 'manual'
            }]

        # Build options array from variants (REQUIRED by Shopify)
        # Shopify requires options to match the option1/option2/option3 values in variants
        options = []

        # Collect all unique option values
        option1_values = set()
        option2_values = set()
        option3_values = set()

        for variant in unique_variants:
            if variant.get('option1'):
                option1_values.add(variant['option1'])
            if variant.get('option2'):
                option2_values.add(variant['option2'])
            if variant.get('option3'):
                option3_values.add(variant['option3'])

        # Build options array
        if option1_values:
            options.append({'name': 'Option 1'})
        if option2_values:
            options.append({'name': 'Option 2'})
        if option3_values:
            options.append({'name': 'Option 3'})

        # If no options, use default Title option
        if not options:
            options = [{'name': 'Title'}]

        logger.info(f"✅ Built {len(options)} option(s) for Shopify")

        shopify_product = {
            'title': self.title,
            'handle': self.handle,
            'body_html': self.body_html,
            'product_type': self.product_type,
            'tags': self.tags,
            'vendor': self.vendor,
            'status': 'active',
            'variants': unique_variants,
            'options': options,
        }

        # Add metafields if any
        metafields = [m.to_shopify_format() for m in self.metafields.all()]
        if metafields:
            shopify_product['metafields'] = metafields

        return shopify_product


class ProductVariant(db.Model):
    """Product variants"""
    __tablename__ = 'product_variants'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    title = db.Column(db.String(500))
    sku = db.Column(db.String(200))
    barcode = db.Column(db.String(200))
    price = db.Column(db.String(20))
    compare_at_price = db.Column(db.String(20))

    option1 = db.Column(db.String(200))
    option2 = db.Column(db.String(200))
    option3 = db.Column(db.String(200))

    requires_shipping = db.Column(db.Boolean, default=True)
    taxable = db.Column(db.Boolean, default=True)

    shopify_variant_id = db.Column(db.String(100))
    shopify_inventory_item_id = db.Column(db.String(100))

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'title': self.title,
            'sku': self.sku,
            'barcode': self.barcode,
            'price': self.price,
            'compare_at_price': self.compare_at_price,
            'option1': self.option1,
            'option2': self.option2,
            'option3': self.option3,
            'requires_shipping': self.requires_shipping,
            'taxable': self.taxable
        }

    def to_shopify_format(self):
        variant = {
            'title': self.title,
            'price': self.price,
            'option1': self.option1 or 'Default',
            'requires_shipping': self.requires_shipping,
            'taxable': self.taxable,
            'inventory_management': None,
            'inventory_policy': 'continue',
            'fulfillment_service': 'manual'
        }

        if self.compare_at_price:
            variant['compare_at_price'] = self.compare_at_price
        if self.sku:
            variant['sku'] = self.sku
        if self.barcode:
            variant['barcode'] = self.barcode
        if self.option2:
            variant['option2'] = self.option2
        if self.option3:
            variant['option3'] = self.option3

        return variant


class ProductImage(db.Model):
    """Product images"""
    __tablename__ = 'product_images'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    original_url = db.Column(db.String(1000))
    processed_url = db.Column(db.String(1000))
    position = db.Column(db.Integer, default=0)

    is_enhanced = db.Column(db.Boolean, default=False)
    shopify_image_id = db.Column(db.String(100))

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'original_url': self.original_url,
            'processed_url': self.processed_url,
            'position': self.position,
            'is_enhanced': self.is_enhanced
        }


class ProductMetafield(db.Model):
    """Product metafields"""
    __tablename__ = 'product_metafields'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    namespace = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text)
    type = db.Column(db.String(100), default='single_line_text_field')

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'namespace': self.namespace,
            'key': self.key,
            'value': self.value,
            'type': self.type
        }

    def to_shopify_format(self):
        return {
            'namespace': self.namespace,
            'key': self.key,
            'value': self.value,
            'type': self.type
        }


# ==================== AI PRODUCTS ====================


class AIProduct(db.Model):
    """Stores AI-enhanced product dupes before pushing to Shopify"""
    __tablename__ = 'ai_products'

    id = db.Column(db.Integer, primary_key=True)
    source_product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    ai_job_id = db.Column(db.Integer, db.ForeignKey('ai_jobs.id'))

    # Product details (AI-enhanced)
    title = db.Column(db.String(500), nullable=False)
    handle = db.Column(db.String(500))
    body_html = db.Column(db.Text)
    product_type = db.Column(db.String(200))
    tags = db.Column(db.Text)
    vendor = db.Column(db.String(200))

    # SEO fields
    seo_title = db.Column(db.String(500))
    seo_description = db.Column(db.Text)

    # Status tracking
    status = db.Column(db.String(50), default='pending')  # pending, approved, rejected, pushed
    shopify_product_id = db.Column(db.String(100))

    # AI generation info
    ai_enhanced = db.Column(db.Boolean, default=True)
    image_prompt = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pushed_at = db.Column(db.DateTime)

    # Relationships
    source_product = db.relationship('Product', backref='ai_dupes', foreign_keys=[source_product_id])
    variants = db.relationship('AIProductVariant', backref='ai_product', lazy='dynamic', cascade='all, delete-orphan')
    images = db.relationship('AIProductImage', backref='ai_product', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'source_product_id': self.source_product_id,
            'ai_job_id': self.ai_job_id,
            'title': self.title,
            'handle': self.handle,
            'body_html': self.body_html,
            'product_type': self.product_type,
            'tags': self.tags,
            'vendor': self.vendor,
            'seo_title': self.seo_title,
            'seo_description': self.seo_description,
            'status': self.status,
            'shopify_product_id': self.shopify_product_id,
            'ai_enhanced': self.ai_enhanced,
            'image_prompt': self.image_prompt,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'pushed_at': self.pushed_at.isoformat() if self.pushed_at else None
        }

        if include_relations:
            data['variants'] = [v.to_dict() for v in self.variants.all()]
            data['images'] = [i.to_dict() for i in self.images.all()]

        return data

    def to_shopify_format(self):
        """Convert to Shopify API format"""
        import logging
        logger = logging.getLogger(__name__)

        # Get all variants
        all_variants = [v.to_shopify_format() for v in self.variants.all()]

        logger.info(f"AI Product '{self.title}': Processing {len(all_variants)} total variants")

        # Remove duplicate variants (same option1, option2, option3)
        # Shopify will reject products with duplicate variants
        seen_variants = set()
        unique_variants = []
        duplicates_removed = 0

        for idx, variant in enumerate(all_variants, 1):
            # Create a tuple of option values for comparison
            variant_key = (
                variant.get('option1', 'Default'),
                variant.get('option2'),
                variant.get('option3')
            )

            if variant_key not in seen_variants:
                seen_variants.add(variant_key)
                unique_variants.append(variant)
                logger.info(f"  ✅ Variant {idx}: {variant.get('title')} (£{variant.get('price')}) - Options: {variant_key}")
            else:
                duplicates_removed += 1
                logger.warning(f"  ⚠️ Variant {idx}: {variant.get('title')} REMOVED (duplicate options: {variant_key})")

        if duplicates_removed > 0:
            logger.warning(f"⚠️ Removed {duplicates_removed} duplicate variant(s) from '{self.title}'")

        logger.info(f"✅ Final: {len(unique_variants)} unique variant(s) will be sent to Shopify")

        # If no variants or all were duplicates, ensure at least one variant
        if not unique_variants:
            logger.warning(f"⚠️ No unique variants found, creating default variant")
            unique_variants = [{
                'title': 'Default',
                'price': '0.00',
                'option1': 'Default',
                'requires_shipping': True,
                'taxable': True,
                'inventory_management': None,
                'inventory_policy': 'continue',
                'fulfillment_service': 'manual'
            }]

        # Build options array from variants (REQUIRED by Shopify)
        # Shopify requires options to match the option1/option2/option3 values in variants
        options = []

        # Collect all unique option values
        option1_values = set()
        option2_values = set()
        option3_values = set()

        for variant in unique_variants:
            if variant.get('option1'):
                option1_values.add(variant['option1'])
            if variant.get('option2'):
                option2_values.add(variant['option2'])
            if variant.get('option3'):
                option3_values.add(variant['option3'])

        # Build options array
        if option1_values:
            options.append({'name': 'Option 1'})
        if option2_values:
            options.append({'name': 'Option 2'})
        if option3_values:
            options.append({'name': 'Option 3'})

        # If no options, use default Title option
        if not options:
            options = [{'name': 'Title'}]

        logger.info(f"✅ Built {len(options)} option(s) for Shopify")

        shopify_product = {
            'title': self.title,
            'handle': self.handle,
            'body_html': self.body_html,
            'product_type': self.product_type,
            'tags': self.tags,
            'vendor': self.vendor,
            'status': 'active',
            'variants': unique_variants,
            'options': options,
        }

        return shopify_product


class AIProductVariant(db.Model):
    """AI Product variants"""
    __tablename__ = 'ai_product_variants'

    id = db.Column(db.Integer, primary_key=True)
    ai_product_id = db.Column(db.Integer, db.ForeignKey('ai_products.id'), nullable=False)

    title = db.Column(db.String(500))
    sku = db.Column(db.String(200))
    barcode = db.Column(db.String(200))
    price = db.Column(db.String(20))
    compare_at_price = db.Column(db.String(20))

    option1 = db.Column(db.String(200))
    option2 = db.Column(db.String(200))
    option3 = db.Column(db.String(200))

    requires_shipping = db.Column(db.Boolean, default=True)
    taxable = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'ai_product_id': self.ai_product_id,
            'title': self.title,
            'sku': self.sku,
            'barcode': self.barcode,
            'price': self.price,
            'compare_at_price': self.compare_at_price,
            'option1': self.option1,
            'option2': self.option2,
            'option3': self.option3,
            'requires_shipping': self.requires_shipping,
            'taxable': self.taxable
        }

    def to_shopify_format(self):
        variant = {
            'title': self.title,
            'price': self.price,
            'option1': self.option1 or 'Default',
            'requires_shipping': self.requires_shipping,
            'taxable': self.taxable,
            'inventory_management': None,
            'inventory_policy': 'continue',
            'fulfillment_service': 'manual'
        }

        if self.compare_at_price:
            variant['compare_at_price'] = self.compare_at_price
        if self.sku:
            variant['sku'] = self.sku
        if self.barcode:
            variant['barcode'] = self.barcode
        if self.option2:
            variant['option2'] = self.option2
        if self.option3:
            variant['option3'] = self.option3

        return variant


class AIProductImage(db.Model):
    """AI Product images"""
    __tablename__ = 'ai_product_images'

    id = db.Column(db.Integer, primary_key=True)
    ai_product_id = db.Column(db.Integer, db.ForeignKey('ai_products.id'), nullable=False)

    image_url = db.Column(db.String(1000))
    position = db.Column(db.Integer, default=0)
    ai_generated = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'ai_product_id': self.ai_product_id,
            'image_url': self.image_url,
            'position': self.position,
            'ai_generated': self.ai_generated
        }


class AIJob(db.Model):
    """Tracks AI dupe creation jobs for bulk product processing"""
    __tablename__ = 'ai_jobs'

    id = db.Column(db.Integer, primary_key=True)
    source_job_id = db.Column(db.Integer, db.ForeignKey('scrape_jobs.id'), nullable=False)
    source_job_task_id = db.Column(db.String(100))
    status = db.Column(db.String(50), default='pending')  # pending, running, completed, error
    push_status = db.Column(db.String(50), default='not_started')  # not_started, in_progress, completed, error
    ai_products_created = db.Column(db.Integer, default=0)
    products_pushed = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    push_started_at = db.Column(db.DateTime)
    push_completed_at = db.Column(db.DateTime)

    # Relationships
    source_job = db.relationship('ScrapeJob', backref='ai_jobs', foreign_keys=[source_job_id])
    ai_products = db.relationship('AIProduct', backref='ai_job', lazy='dynamic', foreign_keys='AIProduct.ai_job_id')

    def to_dict(self):
        return {
            'id': self.id,
            'source_job_id': self.source_job_id,
            'source_job_task_id': self.source_job_task_id,
            'status': self.status,
            'push_status': self.push_status,
            'ai_products_created': self.ai_products_created,
            'products_pushed': self.products_pushed,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'push_started_at': self.push_started_at.isoformat() if self.push_started_at else None,
            'push_completed_at': self.push_completed_at.isoformat() if self.push_completed_at else None
        }
