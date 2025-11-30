"""
Database utilities and service layer
"""

from models import db, ScrapeJob, Product, ProductVariant, ProductImage, ProductMetafield, AIJob, AIProduct
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for database operations"""

    @staticmethod
    def create_scrape_job(task_id, source_url):
        """Create a new scrape job"""
        try:
            job = ScrapeJob(
                task_id=task_id,
                source_url=source_url,
                status='pending'
            )
            db.session.add(job)
            db.session.commit()
            logger.info(f"Created scrape job: {task_id}")
            return job
        except Exception as e:
            logger.error(f"Error creating scrape job: {str(e)}")
            db.session.rollback()
            return None

    @staticmethod
    def update_scrape_job(task_id, **kwargs):
        """Update scrape job status"""
        try:
            job = ScrapeJob.query.filter_by(task_id=task_id).first()
            if job:
                for key, value in kwargs.items():
                    setattr(job, key, value)
                db.session.commit()
                return job
            return None
        except Exception as e:
            logger.error(f"Error updating scrape job: {str(e)}")
            db.session.rollback()
            return None

    @staticmethod
    def get_scrape_job(task_id):
        """Get scrape job by task_id"""
        return ScrapeJob.query.filter_by(task_id=task_id).first()

    @staticmethod
    def save_product(job_id, product_data, enhanced_data=None):
        """Save a scraped product to database"""
        try:
            # Merge original and enhanced data (but preserve mapped options)
            if enhanced_data:
                # Save the correctly mapped options before merge
                mapped_options = product_data.get('options', [])
                product_data = {**product_data, **enhanced_data}
                # Restore the correctly mapped options (don't let original overwrite)
                if mapped_options:
                    product_data['options'] = mapped_options

            # Create product
            # Convert tags list to comma-separated string
            tags_data = product_data.get('tags', '')
            if isinstance(tags_data, list):
                tags_data = ', '.join(tags_data)

            # Extract option names from product options
            option1_name = None
            option2_name = None
            option3_name = None

            options_data = product_data.get('options', [])
            if isinstance(options_data, list):
                for idx, opt in enumerate(options_data):
                    if isinstance(opt, dict):
                        opt_name = opt.get('name', '')
                        if opt_name and opt_name != 'Title':
                            if idx == 0:
                                option1_name = opt_name
                            elif idx == 1:
                                option2_name = opt_name
                            elif idx == 2:
                                option3_name = opt_name

            product = Product(
                job_id=job_id,
                title=product_data.get('title', 'Untitled'),
                handle=product_data.get('handle', ''),
                body_html=product_data.get('body_html', ''),
                product_type=product_data.get('product_type', ''),
                tags=tags_data,
                vendor=product_data.get('vendor', ''),
                option1_name=option1_name,
                option2_name=option2_name,
                option3_name=option3_name,
                seo_title=product_data.get('seo_title', ''),
                seo_description=product_data.get('seo_description', ''),
                status='pending',
                original_data=json.dumps(product_data.get('_original', {}))
            )
            db.session.add(product)
            db.session.flush()  # Get product ID

            # Save variants
            variants_data = product_data.get('variants', [])
            logger.info(f"DEBUG: Saving {len(variants_data)} variants for product '{product_data.get('title', 'Unknown')}'")
            valid_variants_saved = 0

            for variant_data in variants_data:
                # Extract price - handle both string and dict formats
                price_data = variant_data.get('price', '0.00')
                if isinstance(price_data, dict):
                    price_data = str(price_data.get('current', 0))
                elif isinstance(price_data, (int, float)):
                    price_data = str(price_data)

                # CRITICAL: Skip zero-price variants - DO NOT SAVE to database
                try:
                    price_float = float(price_data)
                    if price_float <= 0.01:
                        logger.warning(f"⏭️  SKIPPING zero-price variant: {variant_data.get('title')} (Price: £{price_float})")
                        continue
                except (ValueError, TypeError):
                    logger.warning(f"⏭️  SKIPPING variant with invalid price: {variant_data.get('title')}")
                    continue

                # Extract compare_at_price - handle both string and dict formats
                compare_at_price_data = variant_data.get('compare_at_price')
                if isinstance(compare_at_price_data, dict):
                    compare_at_price_data = str(compare_at_price_data.get('previous', 0))
                elif isinstance(compare_at_price_data, (int, float)):
                    compare_at_price_data = str(compare_at_price_data)

                variant = ProductVariant(
                    product_id=product.id,
                    title=variant_data.get('title', 'Default'),
                    sku=variant_data.get('sku', ''),
                    barcode=variant_data.get('barcode', ''),
                    price=price_data,
                    compare_at_price=compare_at_price_data,
                    option1=variant_data.get('option1', 'Default'),
                    option2=variant_data.get('option2'),
                    option3=variant_data.get('option3'),
                    requires_shipping=variant_data.get('requires_shipping', True),
                    taxable=variant_data.get('taxable', True)
                )
                db.session.add(variant)
                valid_variants_saved += 1

            # CRITICAL: If no valid variants were saved, delete the product and skip
            if valid_variants_saved == 0:
                logger.error(f"❌ SKIPPING ENTIRE PRODUCT: No valid variants (all zero-price or invalid)")
                logger.error(f"   Product: {product.title}")
                db.session.delete(product)
                db.session.flush()
                return None

            logger.info(f"✅ Saved {valid_variants_saved} valid variant(s) for product '{product.title}'")

            # Save images
            images_data = product_data.get('images', [])
            for idx, image_url in enumerate(images_data):
                if isinstance(image_url, dict):
                    image_url = image_url.get('url') or image_url.get('src', '')

                if image_url:
                    image = ProductImage(
                        product_id=product.id,
                        original_url=image_url,
                        position=idx
                    )
                    db.session.add(image)

            # Save metafields
            metafields_data = product_data.get('metafields', [])
            for mf_data in metafields_data:
                metafield = ProductMetafield(
                    product_id=product.id,
                    namespace=mf_data.get('namespace', 'custom'),
                    key=mf_data.get('key'),
                    value=mf_data.get('value'),
                    type=mf_data.get('type', 'single_line_text_field')
                )
                db.session.add(metafield)

            db.session.commit()
            logger.info(f"Saved product to database: {product.title}")
            return product

        except Exception as e:
            logger.error(f"Error saving product: {str(e)}")
            db.session.rollback()
            return None

    @staticmethod
    def get_products(job_id=None, status=None, limit=100, offset=0):
        """Get products with filters"""
        query = Product.query

        if job_id:
            query = query.filter_by(job_id=job_id)

        if status:
            query = query.filter_by(status=status)

        query = query.order_by(Product.created_at.desc())
        query = query.limit(limit).offset(offset)

        return query.all()

    @staticmethod
    def get_product(product_id):
        """Get single product with all relations"""
        return Product.query.get(product_id)

    @staticmethod
    def update_product_status(product_id, status, shopify_product_id=None):
        """Update product status"""
        try:
            product = Product.query.get(product_id)
            if product:
                product.status = status
                if shopify_product_id:
                    product.shopify_product_id = shopify_product_id
                if status == 'pushed':
                    product.pushed_at = datetime.utcnow()
                db.session.commit()
                return product
            return None
        except Exception as e:
            logger.error(f"Error updating product status: {str(e)}")
            db.session.rollback()
            return None

    @staticmethod
    def bulk_update_status(product_ids, status):
        """Bulk update product status"""
        try:
            Product.query.filter(Product.id.in_(product_ids)).update(
                {'status': status},
                synchronize_session=False
            )
            db.session.commit()
            logger.info(f"Bulk updated {len(product_ids)} products to {status}")
            return True
        except Exception as e:
            logger.error(f"Error bulk updating: {str(e)}")
            db.session.rollback()
            return False

    @staticmethod
    def delete_product(product_id):
        """Delete a product"""
        try:
            product = Product.query.get(product_id)
            if product:
                db.session.delete(product)
                db.session.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            db.session.rollback()
            return False

    @staticmethod
    def get_stats():
        """Get database statistics"""
        try:
            total_jobs = ScrapeJob.query.count()
            total_products = Product.query.count()
            pending_products = Product.query.filter_by(status='pending').count()
            approved_products = Product.query.filter_by(status='approved').count()
            pushed_products = Product.query.filter_by(status='pushed').count()

            # AI job statistics
            total_ai_jobs = AIJob.query.count()
            ai_products_created = AIProduct.query.count()
            ai_products_pushed = AIProduct.query.filter_by(status='pushed').count()

            return {
                'total_jobs': total_jobs,
                'total_products': total_products,
                'pending_products': pending_products,
                'approved_products': approved_products,
                'pushed_products': pushed_products,
                'total_ai_jobs': total_ai_jobs,
                'ai_products_created': ai_products_created,
                'ai_products_pushed': ai_products_pushed
            }
        except Exception as e:
            logger.error(f"Error getting stats: {str(e)}")
            return {}
