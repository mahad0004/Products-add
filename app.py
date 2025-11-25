"""
Shopify Product Automation Flask Application with Database
Enhanced version with UI dashboard and product management
"""

from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for
from functools import wraps
import os
import logging
import time
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import threading

from models import db, ScrapeJob, Product, AIProduct, AIProductVariant, AIProductImage, AIJob
from database import DatabaseService
from services.apify_service import ApifyService
from services.shopify_service import ShopifyService
from services.openai_service import OpenAIService
from services.gemini_service import GeminiService
from services.product_mapper import ProductMapper
from services.image_processor import ImageProcessor

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ENVIRONMENT VARIABLES VALIDATION ====================
# Check for required environment variables at startup
REQUIRED_ENV_VARS = {
    'SHOPIFY_SHOP_URL': 'Shopify store URL (e.g., https://your-store.myshopify.com)',
    'SHOPIFY_ACCESS_TOKEN': 'Shopify Admin API access token',
    'APIFY_API_TOKEN': 'Apify API token for product scraping',
    'OPENAI_API_KEY': 'OpenAI API key for content enhancement',
    'GOOGLE_API_KEY': 'Google Gemini API key for image editing'
}

missing_vars = []
for var_name, var_description in REQUIRED_ENV_VARS.items():
    if not os.getenv(var_name):
        missing_vars.append(f"  - {var_name}: {var_description}")

if missing_vars:
    error_message = "\n" + "="*80 + "\n"
    error_message += "❌ MISSING REQUIRED ENVIRONMENT VARIABLES\n"
    error_message += "="*80 + "\n"
    error_message += "The following environment variables are required but not set:\n\n"
    error_message += "\n".join(missing_vars)
    error_message += "\n\n"
    error_message += "📝 To fix this:\n"
    error_message += "1. Create a .env file in the project root\n"
    error_message += "2. Copy .env.example to .env\n"
    error_message += "3. Fill in all required values\n"
    error_message += "\n"
    error_message += "For Railway deployment:\n"
    error_message += "- Set these variables in Railway dashboard under 'Variables' tab\n"
    error_message += "- See .env.example for all required variables\n"
    error_message += "="*80 + "\n"
    logger.error(error_message)
    raise EnvironmentError(error_message)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-this-in-production')

# Login credentials (simple single-user system)
USERNAME = 'Mahad'
PASSWORD = 'Mahad'

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///shopify_automation.db?timeout=30')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_size': 20,  # Increased for parallel processing
    'max_overflow': 10,
    'connect_args': {'timeout': 30, 'check_same_thread': False}
}

# Initialize database
db.init_app(app)

# Create tables and detect stopped jobs
with app.app_context():
    db.create_all()
    logger.info("Database tables created successfully")

    # Detect AI jobs that were running when server stopped and mark them as 'stopped'
    stuck_jobs = AIJob.query.filter_by(status='running').all()
    if stuck_jobs:
        logger.warning(f"Found {len(stuck_jobs)} AI jobs stuck in 'running' state - marking as 'stopped'")
        for job in stuck_jobs:
            job.status = 'stopped'
            job.error_message = 'Job was interrupted (server restart or crash)'
        db.session.commit()
        logger.info(f"Marked {len(stuck_jobs)} jobs as 'stopped' - these can be resumed")

# Initialize services (strip whitespace from API keys to prevent header errors)
apify_service = ApifyService(os.getenv('APIFY_API_TOKEN', '').strip())
shopify_service = ShopifyService(
    shop_url=os.getenv('SHOPIFY_SHOP_URL', '').strip(),
    access_token=os.getenv('SHOPIFY_ACCESS_TOKEN', '').strip()
)
openai_service = OpenAIService(os.getenv('OPENAI_API_KEY', '').strip())
gemini_service = GeminiService(os.getenv('GOOGLE_API_KEY', '').strip())
product_mapper = ProductMapper()
image_processor = ImageProcessor()
db_service = DatabaseService()

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=3)

# Parallel processing executor (configurable workers for Pro Mode)
# Default: 2 workers for Pro Mode parallel processing (conservative to avoid rate limits)
PARALLEL_WORKERS = int(os.getenv('PARALLEL_WORKERS', 2))

# ==================== GLOBAL RATE LIMITERS ====================
# These ensure we never hit API rate limits for Gemini, OpenAI, or Shopify
# Semaphores limit concurrent API calls across all parallel workers

# Gemini Rate Limiter: Max 2 concurrent calls (conservative)
gemini_rate_limiter = threading.Semaphore(2)
GEMINI_DELAY = float(os.getenv('GEMINI_DELAY', 1.0))  # 1 second delay after each Gemini call

# OpenAI Rate Limiter: Max 2 concurrent calls
openai_rate_limiter = threading.Semaphore(2)
OPENAI_DELAY = float(os.getenv('OPENAI_DELAY', 0.5))  # 0.5 second delay after each OpenAI call

# Shopify Rate Limiter: Max 1 concurrent call (Shopify has strict 2 req/sec limit)
shopify_rate_limiter = threading.Semaphore(1)
SHOPIFY_DELAY = float(os.getenv('SHOPIFY_DELAY', 0.6))  # 0.6 second delay after each Shopify call (under 2/sec)

# Global progress tracking for pushing to Shopify
push_progress = {
    'total': 0,
    'current': 0,
    'status': 'idle',  # idle, running, completed, error, cancelled
    'message': '',
    'cancel_requested': False
}

# Global progress tracking for AI products
ai_push_progress = {
    'total': 0,
    'current': 0,
    'status': 'idle',  # idle, running, completed, error, cancelled
    'message': '',
    'cancel_requested': False
}

# Thread-safe counters for parallel processing
class ThreadSafeCounter:
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()

    def increment(self):
        with self.lock:
            self.value += 1
            return self.value

    def get(self):
        with self.lock:
            return self.value


# ==================== AUTH MIDDLEWARE ====================

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function


# ==================== ROUTES ====================

@app.route('/login')
def login_page():
    """Login page"""
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def login():
    """Handle login"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            logger.info(f"User {username} logged in successfully")
            return jsonify({'message': 'Login successful'})
        else:
            return jsonify({'error': 'Invalid username or password'}), 401

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Login failed'}), 500


@app.route('/api/logout', methods=['POST'])
def logout():
    """Handle logout"""
    session.clear()
    return jsonify({'message': 'Logged out successfully'})


@app.route('/')
@login_required
def index():
    """Main dashboard"""
    return render_template('dashboard.html')


@app.route('/scrape')
@login_required
def scrape_page():
    """Scraping page"""
    return render_template('scrape.html')


@app.route('/products')
@login_required
def products_page():
    """Products management page"""
    return render_template('products.html')


@app.route('/ai-products')
@login_required
def ai_products_page():
    """AI Products management page"""
    return render_template('ai_products.html')


@app.route('/ai-job/<int:ai_job_id>')
@login_required
def ai_job_page(ai_job_id):
    """AI Job page - shows AI products and auto-pushes to Shopify"""
    return render_template('ai_job.html', ai_job_id=ai_job_id)


@app.route('/static/<path:path>')
def send_static(path):
    """Serve static files"""
    return send_from_directory('static', path)


# ==================== API ENDPOINTS ====================

@app.route('/api/scrape', methods=['POST'])
@login_required
def start_scrape():
    """Start scraping and save to database"""
    try:
        data = request.get_json()
        url = data.get('url')
        max_products = data.get('max_products', 200)

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        if not url.startswith('http'):
            return jsonify({'error': 'Invalid URL format'}), 400

        # Create scrape job in database
        task_id = f"task_{os.urandom(8).hex()}"
        job = db_service.create_scrape_job(task_id, url)

        if not job:
            return jsonify({'error': 'Failed to create scrape job'}), 500

        logger.info(f"Starting scrape for URL: {url}, task_id: {task_id}")

        # Start workflow asynchronously with app context
        executor.submit(run_workflow_with_context, task_id, url, max_products)

        return jsonify({
            'message': 'Scraping started successfully',
            'task_id': task_id,
            'job_id': job.id,
            'status': 'processing'
        }), 202

    except Exception as e:
        logger.error(f"Error starting scrape: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Get all scrape jobs"""
    try:
        jobs = ScrapeJob.query.order_by(ScrapeJob.created_at.desc()).limit(50).all()
        return jsonify({
            'jobs': [job.to_dict() for job in jobs]
        })
    except Exception as e:
        logger.error(f"Error getting jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/<task_id>', methods=['GET'])
def get_job(task_id):
    """Get job status"""
    try:
        job = db_service.get_scrape_job(task_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify(job.to_dict())
    except Exception as e:
        logger.error(f"Error getting job: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products', methods=['GET'])
def get_products():
    """Get products with filters"""
    try:
        job_id = request.args.get('job_id', type=int)
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        products = db_service.get_products(job_id, status, limit, offset)

        return jsonify({
            'products': [p.to_dict(include_relations=True) for p in products],
            'total': Product.query.count()
        })
    except Exception as e:
        logger.error(f"Error getting products: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """Get single product with full details"""
    try:
        product = db_service.get_product(product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        return jsonify(product.to_dict(include_relations=True))
    except Exception as e:
        logger.error(f"Error getting product: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Update product details"""
    try:
        product = db_service.get_product(product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        data = request.get_json()

        # Update fields
        if 'title' in data:
            product.title = data['title']
        if 'body_html' in data:
            product.body_html = data['body_html']
        if 'product_type' in data:
            product.product_type = data['product_type']
        if 'tags' in data:
            product.tags = data['tags']
        if 'vendor' in data:
            product.vendor = data['vendor']
        if 'status' in data:
            product.status = data['status']

        db.session.commit()

        return jsonify({
            'message': 'Product updated successfully',
            'product': product.to_dict(include_relations=True)
        })
    except Exception as e:
        logger.error(f"Error updating product: {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product"""
    try:
        if db_service.delete_product(product_id):
            return jsonify({'message': 'Product deleted successfully'})
        else:
            return jsonify({'error': 'Product not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting product: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/bulk-action', methods=['POST'])
def bulk_action():
    """Perform bulk action on products"""
    try:
        data = request.get_json()
        action = data.get('action')
        product_ids = data.get('product_ids', [])

        if not action or not product_ids:
            return jsonify({'error': 'Action and product_ids required'}), 400

        if action == 'approve':
            db_service.bulk_update_status(product_ids, 'approved')
            return jsonify({'message': f'Approved {len(product_ids)} products'})

        elif action == 'reject':
            db_service.bulk_update_status(product_ids, 'rejected')
            return jsonify({'message': f'Rejected {len(product_ids)} products'})

        elif action == 'delete':
            for product_id in product_ids:
                db_service.delete_product(product_id)
            return jsonify({'message': f'Deleted {len(product_ids)} products'})

        elif action == 'push_to_shopify':
            # Push products to Shopify asynchronously with progress tracking
            global push_progress
            push_progress = {
                'total': len(product_ids),
                'current': 0,
                'status': 'running',
                'message': 'Starting to push products to Shopify...',
                'cancel_requested': False
            }

            # Run in background
            executor.submit(push_products_async, product_ids)

            return jsonify({
                'message': 'Push to Shopify started',
                'total': len(product_ids),
                'status': 'started'
            })

        else:
            return jsonify({'error': 'Invalid action'}), 400

    except Exception as e:
        logger.error(f"Error in bulk action: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    try:
        stats = db_service.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/push-progress', methods=['GET'])
def get_push_progress():
    """Get push to Shopify progress"""
    return jsonify(push_progress)


@app.route('/api/cancel-push', methods=['POST'])
def cancel_push():
    """Cancel ongoing push to Shopify"""
    global push_progress
    if push_progress['status'] == 'running':
        push_progress['cancel_requested'] = True
        push_progress['message'] = 'Cancellation requested...'
        logger.info("Push cancellation requested")
        return jsonify({'message': 'Cancellation requested'})
    else:
        return jsonify({'message': 'No push in progress'})


# ==================== AI PRODUCTS API ====================

@app.route('/api/ai-products', methods=['GET'])
@login_required
def get_ai_products():
    """Get AI products with filters"""
    try:
        ai_job_id = request.args.get('ai_job_id', type=int)
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        query = AIProduct.query

        if ai_job_id:
            query = query.filter_by(ai_job_id=ai_job_id)

        if status:
            query = query.filter_by(status=status)

        query = query.order_by(AIProduct.created_at.desc())
        query = query.limit(limit).offset(offset)

        ai_products = query.all()

        return jsonify({
            'products': [p.to_dict(include_relations=True) for p in ai_products],
            'total': AIProduct.query.count()
        })
    except Exception as e:
        logger.error(f"Error getting AI products: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/create-ai-dupes', methods=['POST'])
@login_required
def create_ai_dupes():
    """Create AI-enhanced dupes from source products using OpenAI + Gemini"""
    try:
        data = request.get_json()
        product_ids = data.get('product_ids', [])

        if not product_ids:
            return jsonify({'error': 'No product IDs provided'}), 400

        created_count = 0
        errors = []

        for product_id in product_ids:
            source_product = Product.query.get(product_id)
            if not source_product:
                logger.warning(f"Product {product_id} not found, skipping")
                errors.append(f"Product {product_id} not found")
                continue

            # Check if AI dupe already exists
            existing_dupe = AIProduct.query.filter_by(source_product_id=product_id).first()
            if existing_dupe:
                logger.info(f"AI dupe already exists for product {product_id}, skipping")
                errors.append(f"AI dupe already exists for product {product_id}")
                continue

            try:
                logger.info(f"Creating AI-enhanced dupe for product: {source_product.title}")

                # Get original product data (JSON)
                import json
                original_data = {}
                if source_product.original_data:
                    try:
                        original_data = json.loads(source_product.original_data)
                    except:
                        original_data = {}

                # Get price from first variant
                price = "0.00"
                if source_product.variants.count() > 0:
                    first_variant = source_product.variants.first()
                    price = first_variant.price or "0.00"

                # STEP 1: Use OpenAI to enhance product description
                logger.info(f"Enhancing product description with OpenAI...")
                product_data_for_ai = {
                    'title': source_product.title,
                    'description': source_product.body_html or '',
                    'body_html': source_product.body_html or '',
                    'price': price,
                    'product_type': source_product.product_type or '',
                    'vendor': source_product.vendor or ''
                }

                enhanced_product = openai_service.enhance_product_description(product_data_for_ai)

                # STEP 2: Use Nano Banana to edit images
                logger.info(f"Editing images with Nano Banana 🍌...")
                ai_image_urls = []
                image_prompt = ""

                # Get first image from source product
                first_image = source_product.images.first()
                if first_image and first_image.original_url:
                    # Image 1: Edit to main front view
                    logger.info(f"Editing Image 1 with Nano Banana: Main front view...")
                    edited_url_1 = gemini_service.edit_product_image(
                        first_image.original_url,
                        source_product.title,
                        variation="main"
                    )

                    if edited_url_1:
                        ai_image_urls.append(edited_url_1)
                        logger.info(f"✅ Nano Banana: Edited image 1/2 (Main view)")
                    else:
                        logger.warning(f"Nano Banana edit failed, using original image as fallback")
                        ai_image_urls.append(first_image.original_url)

                    # Image 2: Edit to 45-degree angled view
                    logger.info(f"Editing Image 2 with Nano Banana: 45-degree angled view...")
                    edited_url_2 = gemini_service.edit_product_image(
                        first_image.original_url,
                        source_product.title,
                        variation="angle1"
                    )

                    if edited_url_2:
                        ai_image_urls.append(edited_url_2)
                        logger.info(f"✅ Nano Banana: Edited image 2/2 (Angled view)")
                    else:
                        logger.warning(f"Nano Banana edit failed, using original image as fallback")
                        ai_image_urls.append(first_image.original_url)

                    image_prompt = f"Nano Banana edited variations of {source_product.title}"
                else:
                    # Fallback if no images
                    logger.warning(f"No images found for product {product_id}, using placeholders")
                    ai_image_urls = [
                        f"https://dummyimage.com/800x800/667eea/ffffff.png&text=AI+Product+1",
                        f"https://dummyimage.com/800x800/764ba2/ffffff.png&text=AI+Product+2"
                    ]
                    image_prompt = f"Professional e-commerce photo of {source_product.title}"

                # Create AI product with enhanced data
                ai_product = AIProduct(
                    source_product_id=source_product.id,
                    title=enhanced_product.get('title', source_product.title),
                    handle=enhanced_product.get('slug', source_product.handle),
                    body_html=enhanced_product.get('body_html', source_product.body_html),
                    product_type=source_product.product_type,
                    tags=enhanced_product.get('tags', source_product.tags),
                    vendor=source_product.vendor,
                    seo_title=enhanced_product.get('seo_title', source_product.seo_title),
                    seo_description=enhanced_product.get('seo_description', source_product.seo_description),
                    status='pending',
                    ai_enhanced=True,
                    image_prompt=image_prompt
                )
                db.session.add(ai_product)
                db.session.flush()

                # Copy ALL variants (prices already doubled in source products from adjust_prices)
                for variant in source_product.variants:
                    # Source products already have doubled prices from adjust_prices()
                    # No need to double again - just copy the price as-is
                    variant_price = float(variant.price) if variant.price else 0
                    variant_compare_price = float(variant.compare_at_price) if variant.compare_at_price else None

                    # CRITICAL FIX: Parse variant title to extract option values
                    # Many source products have option1='Default' because they were scraped before the fix
                    # Parse title like "Galvanised / Bolt Down (flanged) excluding Bolts" into distinct options
                    option1_value = variant.option1 if variant.option1 and variant.option1 != 'Default' else None
                    option2_value = variant.option2
                    option3_value = variant.option3

                    # If no valid option1, parse from title
                    if not option1_value and variant.title:
                        title_parts = variant.title.split('/')
                        title_parts = [part.strip() for part in title_parts if part.strip()]

                        if len(title_parts) >= 1:
                            option1_value = title_parts[0]
                        if len(title_parts) >= 2:
                            option2_value = title_parts[1]
                        if len(title_parts) >= 3:
                            option3_value = title_parts[2]

                    # Final fallback
                    if not option1_value:
                        option1_value = variant.title if variant.title else 'Default'

                    ai_variant = AIProductVariant(
                        ai_product_id=ai_product.id,
                        title=variant.title,
                        sku=variant.sku,
                        barcode=variant.barcode,
                        price=variant_price,
                        compare_at_price=variant_compare_price,
                        option1=option1_value,
                        option2=option2_value,
                        option3=option3_value,
                        requires_shipping=variant.requires_shipping,
                        taxable=variant.taxable
                    )
                    db.session.add(ai_variant)

                # Add AI-generated images
                for idx, ai_image_url in enumerate(ai_image_urls):
                    ai_image = AIProductImage(
                        ai_product_id=ai_product.id,
                        image_url=ai_image_url,
                        position=idx,
                        ai_generated=True
                    )
                    db.session.add(ai_image)

                created_count += 1
                logger.info(f"Successfully created AI-enhanced product: {ai_product.title}")

            except Exception as e:
                logger.error(f"Error processing product {product_id}: {str(e)}", exc_info=True)
                errors.append(f"Error with product {product_id}: {str(e)}")
                continue

        db.session.commit()

        response_message = f'Created {created_count} AI-enhanced product dupe(s) using OpenAI + Gemini'
        if errors:
            response_message += f'. Errors: {len(errors)}'

        logger.info(response_message)
        return jsonify({
            'message': response_message,
            'created': created_count,
            'errors': errors[:5]  # Return first 5 errors only
        })

    except Exception as e:
        logger.error(f"Error creating AI dupes: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/create-ai-job', methods=['POST'])
@login_required
def create_ai_job():
    """Create an AI job to process all products from a scrape job"""
    try:
        data = request.get_json()
        job_id = data.get('job_id')
        fast_mode = data.get('fast_mode', False)  # NEW: Skip AI image generation if True
        product_limit = data.get('product_limit')  # NEW: Limit number of products to process

        if not job_id:
            return jsonify({'error': 'job_id is required'}), 400

        # Get the scrape job
        scrape_job = ScrapeJob.query.get(job_id)
        if not scrape_job:
            return jsonify({'error': 'Scrape job not found'}), 404

        # Check if AI job already exists for this scrape job
        existing_ai_job = AIJob.query.filter_by(source_job_id=job_id).first()
        if existing_ai_job:
            return jsonify({'error': 'AI job already exists for this scrape job', 'ai_job_id': existing_ai_job.id}), 400

        # Create AI job
        ai_job = AIJob(
            source_job_id=job_id,
            source_job_task_id=scrape_job.task_id,
            status='pending',
            ai_products_created=0,
            products_pushed=0
        )
        db.session.add(ai_job)
        db.session.commit()

        logger.info(f"Created AI job {ai_job.id} for scrape job {job_id} (fast_mode={fast_mode}, product_limit={product_limit})")

        # Start AI processing in background with fast_mode option
        executor.submit(process_ai_job_async, ai_job.id, fast_mode, product_limit)

        mode_message = " (FAST MODE - 1 image, no AI)" if fast_mode else f" (PRO MODE - {PARALLEL_WORKERS} parallel workers, rate-limited)"
        limit_message = f" - Testing with {product_limit} products" if product_limit else ""
        return jsonify({
            'message': f'AI job created successfully for scrape job {job_id}{mode_message}{limit_message}',
            'ai_job_id': ai_job.id,
            'status': 'started',
            'fast_mode': fast_mode,
            'product_limit': product_limit
        })

    except Exception as e:
        logger.error(f"Error creating AI job: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai-jobs', methods=['GET'])
@login_required
def get_ai_jobs():
    """Get all AI jobs"""
    try:
        ai_jobs = AIJob.query.order_by(AIJob.created_at.desc()).limit(50).all()
        return jsonify({
            'ai_jobs': [ai_job.to_dict() for ai_job in ai_jobs]
        })
    except Exception as e:
        logger.error(f"Error getting AI jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/resume-ai-job/<int:ai_job_id>', methods=['POST'])
@login_required
def resume_ai_job(ai_job_id):
    """Resume a stopped/error AI job from where it left off"""
    try:
        # Get the AI job
        ai_job = AIJob.query.get(ai_job_id)
        if not ai_job:
            return jsonify({'error': 'AI job not found'}), 404

        # Check if job is in a resumable state
        if ai_job.status == 'completed':
            return jsonify({'error': 'Job already completed'}), 400

        if ai_job.status == 'running':
            return jsonify({'error': 'Job is already running'}), 400

        # Check how many products were already processed
        processed_count = AIProduct.query.filter_by(ai_job_id=ai_job_id).count()
        source_job = ScrapeJob.query.get(ai_job.source_job_id)
        if not source_job:
            return jsonify({'error': 'Source job not found'}), 404

        total_products = Product.query.filter_by(job_id=source_job.id).count()
        remaining = total_products - processed_count

        logger.info(f"Resuming AI job {ai_job_id}: {processed_count}/{total_products} already processed, {remaining} remaining")

        # Reset error status and start processing
        ai_job.status = 'pending'
        ai_job.error_message = None
        db.session.commit()

        # Determine fast_mode from existing AI products (if any exist)
        fast_mode = False
        if processed_count > 0:
            sample_product = AIProduct.query.filter_by(ai_job_id=ai_job_id).first()
            if sample_product:
                # Fast mode has 1 image, Pro mode has 2
                image_count = AIProductImage.query.filter_by(ai_product_id=sample_product.id).count()
                fast_mode = (image_count == 1)

        # Start AI processing in background (will skip already-processed products)
        executor.submit(process_ai_job_async, ai_job_id, fast_mode, None)

        mode_name = "FAST MODE" if fast_mode else "PRO MODE"
        return jsonify({
            'message': f'AI job {ai_job_id} resumed successfully',
            'ai_job_id': ai_job_id,
            'status': 'started',
            'already_processed': processed_count,
            'remaining': remaining,
            'mode': mode_name
        })

    except Exception as e:
        logger.error(f"Error resuming AI job: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai-products/bulk-action', methods=['POST'])
@login_required
def ai_bulk_action():
    """Perform bulk action on AI products"""
    try:
        data = request.get_json()
        action = data.get('action')
        ai_product_ids = data.get('product_ids', [])

        if not action or not ai_product_ids:
            return jsonify({'error': 'Action and product_ids required'}), 400

        if action == 'approve':
            for ai_product_id in ai_product_ids:
                ai_product = AIProduct.query.get(ai_product_id)
                if ai_product:
                    ai_product.status = 'approved'
            db.session.commit()
            return jsonify({'message': f'Approved {len(ai_product_ids)} AI products'})

        elif action == 'reject':
            for ai_product_id in ai_product_ids:
                ai_product = AIProduct.query.get(ai_product_id)
                if ai_product:
                    ai_product.status = 'rejected'
            db.session.commit()
            return jsonify({'message': f'Rejected {len(ai_product_ids)} AI products'})

        elif action == 'delete':
            for ai_product_id in ai_product_ids:
                ai_product = AIProduct.query.get(ai_product_id)
                if ai_product:
                    db.session.delete(ai_product)
            db.session.commit()
            return jsonify({'message': f'Deleted {len(ai_product_ids)} AI products'})

        elif action == 'push_to_shopify':
            # Get AI Job ID from first product (all products should be from same AI job)
            ai_job_id = data.get('ai_job_id')
            if not ai_job_id and ai_product_ids:
                first_product = AIProduct.query.get(ai_product_ids[0])
                if first_product:
                    ai_job_id = first_product.ai_job_id

            # Check if push is already in progress for this AI job
            if ai_job_id:
                ai_job = AIJob.query.get(ai_job_id)
                if ai_job and ai_job.push_status == 'in_progress':
                    return jsonify({
                        'message': 'Push already in progress for this AI job',
                        'status': 'already_running'
                    })

            # Push AI products to Shopify asynchronously with progress tracking
            global ai_push_progress
            ai_push_progress = {
                'total': len(ai_product_ids),
                'current': 0,
                'status': 'running',
                'message': 'Starting to push AI products to Shopify...',
                'cancel_requested': False,
                'ai_job_id': ai_job_id
            }

            # Run in background
            executor.submit(push_ai_products_async_with_job, ai_product_ids, ai_job_id)

            return jsonify({
                'message': 'Push to Shopify started',
                'total': len(ai_product_ids),
                'status': 'started'
            })

        else:
            return jsonify({'error': 'Invalid action'}), 400

    except Exception as e:
        logger.error(f"Error in AI bulk action: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai-push-progress', methods=['GET'])
@login_required
def get_ai_push_progress():
    """Get AI products push to Shopify progress"""
    return jsonify(ai_push_progress)


@app.route('/api/cancel-ai-push', methods=['POST'])
@login_required
def cancel_ai_push():
    """Cancel ongoing AI products push to Shopify"""
    global ai_push_progress
    if ai_push_progress['status'] == 'running':
        ai_push_progress['cancel_requested'] = True
        ai_push_progress['message'] = 'Cancellation requested...'
        logger.info("AI push cancellation requested")
        return jsonify({'message': 'Cancellation requested'})
    else:
        return jsonify({'message': 'No AI push in progress'})


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'shopify-automation'}), 200


# ==================== WORKFLOW FUNCTIONS ====================

def process_single_product(source_product, ai_job_id, fast_mode, created_counter, pushed_counter):
    """
    Process a single product: Create AI product and push to Shopify
    Thread-safe function for parallel processing

    Returns: tuple (success: bool, error_message: str or None)
    """
    with app.app_context():
        try:
            product_id = source_product.id
            logger.info(f"[AI Job {ai_job_id}] Processing product: {source_product.title}")

            # Check if AI dupe already exists
            existing_dupe = AIProduct.query.filter_by(source_product_id=product_id).first()
            if existing_dupe:
                logger.info(f"[AI Job {ai_job_id}] AI dupe already exists for product {product_id}, skipping creation")

                # If exists but not pushed, push it now
                if not existing_dupe.shopify_product_id:
                    logger.info(f"[AI Job {ai_job_id}] Pushing existing AI product to Shopify...")
                    if push_ai_product_to_shopify(existing_dupe.id):
                        pushed_counter.increment()
                        logger.info(f"[AI Job {ai_job_id}] Successfully pushed existing product")

                return (True, None)

            # Get price from first variant
            price = "0.00"
            if source_product.variants.count() > 0:
                first_variant = source_product.variants.first()
                price = first_variant.price or "0.00"

            # STEP 1: Use OpenAI to enhance product description (with rate limiting)
            product_data_for_ai = {
                'title': source_product.title,
                'description': source_product.body_html or '',
                'body_html': source_product.body_html or '',
                'price': price,
                'product_type': source_product.product_type or '',
                'vendor': source_product.vendor or ''
            }

            # Rate-limited OpenAI call
            with openai_rate_limiter:
                logger.info(f"[AI Job {ai_job_id}] 🔄 OpenAI: Enhancing product description...")
                enhanced_product = openai_service.enhance_product_description(product_data_for_ai)
                time.sleep(OPENAI_DELAY)  # Delay after OpenAI call
                logger.info(f"[AI Job {ai_job_id}] ✅ OpenAI: Description enhanced")

            # STEP 2: Use Gemini to generate images (or skip in fast mode)
            ai_image_urls = []
            image_prompt = ""

            if fast_mode:
                # ⚡ FAST MODE: Skip AI image generation, use 1 original image only
                first_image = source_product.images.first()
                if first_image and first_image.original_url:
                    ai_image_urls.append(first_image.original_url)
                else:
                    ai_image_urls = [
                        f"https://dummyimage.com/800x800/4A90E2/ffffff.png&text=Fast+Mode+Image"
                    ]
                image_prompt = f"Product: {source_product.title}"
            else:
                # 🍌 PRO MODE: Edit images with Nano Banana (rate-limited)
                first_image = source_product.images.first()
                if first_image and first_image.original_url:
                    # Image 1: Edit to main front view (rate-limited)
                    with gemini_rate_limiter:
                        logger.info(f"[AI Job {ai_job_id}] 🍌 Nano Banana: Editing image 1/2 (Main front view)...")
                        edited_url_1 = gemini_service.edit_product_image(
                            first_image.original_url,
                            source_product.title,
                            variation="main"
                        )
                        time.sleep(GEMINI_DELAY)  # Delay after Gemini call
                        logger.info(f"[AI Job {ai_job_id}] ✅ Nano Banana: Image 1/2 edited")

                    if edited_url_1:
                        ai_image_urls.append(edited_url_1)
                        logger.info(f"[AI Job {ai_job_id}] ✅ Using AI-edited image 1/2")
                    else:
                        logger.warning(f"[AI Job {ai_job_id}] ⚠️ Gemini editing failed for image 1/2 - falling back to original image")
                        ai_image_urls.append(first_image.original_url)

                    # Image 2: Edit to top-down angled view (rate-limited)
                    with gemini_rate_limiter:
                        logger.info(f"[AI Job {ai_job_id}] 🍌 Nano Banana: Editing image 2/2 (Top-down angled view)...")
                        edited_url_2 = gemini_service.edit_product_image(
                            first_image.original_url,
                            source_product.title,
                            variation="angle1"
                        )
                        time.sleep(GEMINI_DELAY)  # Delay after Gemini call
                        logger.info(f"[AI Job {ai_job_id}] ✅ Nano Banana: Image 2/2 edited")

                    if edited_url_2:
                        ai_image_urls.append(edited_url_2)
                        logger.info(f"[AI Job {ai_job_id}] ✅ Using AI-edited image 2/2")
                    else:
                        logger.warning(f"[AI Job {ai_job_id}] ⚠️ Gemini editing failed for image 2/2 - falling back to original image")
                        ai_image_urls.append(first_image.original_url)

                    image_prompt = f"Nano Banana edited variations of {source_product.title}"
                else:
                    ai_image_urls = [
                        f"https://dummyimage.com/800x800/667eea/ffffff.png&text=AI+Product+1",
                        f"https://dummyimage.com/800x800/764ba2/ffffff.png&text=AI+Product+2"
                    ]
                    image_prompt = f"Professional e-commerce photo of {source_product.title}"

            # STEP 3: Create AI product in database
            ai_product = AIProduct(
                source_product_id=source_product.id,
                ai_job_id=ai_job_id,
                title=enhanced_product.get('title', source_product.title),
                handle=enhanced_product.get('slug', source_product.handle),
                body_html=enhanced_product.get('body_html', source_product.body_html),
                product_type=source_product.product_type,
                tags=enhanced_product.get('tags', source_product.tags),
                vendor=source_product.vendor,
                seo_title=enhanced_product.get('seo_title', source_product.seo_title),
                seo_description=enhanced_product.get('seo_description', source_product.seo_description),
                status='pending',
                ai_enhanced=True,
                image_prompt=image_prompt
            )
            db.session.add(ai_product)
            db.session.flush()

            # Copy ALL variants (prices already doubled in source products from adjust_prices)
            for variant in source_product.variants:
                # Source products already have doubled prices from adjust_prices()
                # No need to double again - just copy the price as-is
                variant_price = float(variant.price) if variant.price else 0
                variant_compare_price = float(variant.compare_at_price) if variant.compare_at_price else None

                # CRITICAL FIX: Parse variant title to extract option values
                # Many source products have option1='Default' because they were scraped before the fix
                # Parse title like "Galvanised / Bolt Down (flanged) excluding Bolts" into distinct options
                option1_value = variant.option1 if variant.option1 and variant.option1 != 'Default' else None
                option2_value = variant.option2
                option3_value = variant.option3

                # If no valid option1, parse from title
                if not option1_value and variant.title:
                    title_parts = variant.title.split('/')
                    title_parts = [part.strip() for part in title_parts if part.strip()]

                    if len(title_parts) >= 1:
                        option1_value = title_parts[0]
                    if len(title_parts) >= 2:
                        option2_value = title_parts[1]
                    if len(title_parts) >= 3:
                        option3_value = title_parts[2]

                # Final fallback
                if not option1_value:
                    option1_value = variant.title if variant.title else 'Default'

                ai_variant = AIProductVariant(
                    ai_product_id=ai_product.id,
                    title=variant.title,
                    sku=variant.sku,
                    barcode=variant.barcode,
                    price=variant_price,
                    compare_at_price=variant_compare_price,
                    option1=option1_value,
                    option2=option2_value,
                    option3=option3_value,
                    requires_shipping=variant.requires_shipping,
                    taxable=variant.taxable
                )
                db.session.add(ai_variant)

            # Add AI-generated images
            for img_idx, ai_image_url in enumerate(ai_image_urls):
                ai_image = AIProductImage(
                    ai_product_id=ai_product.id,
                    image_url=ai_image_url,
                    position=img_idx,
                    ai_generated=True
                )
                db.session.add(ai_image)

            # Commit AI product to database
            db.session.commit()
            created_counter.increment()

            logger.info(f"[AI Job {ai_job_id}] Created AI product: {ai_product.title}")

            # STEP 4: Push to Shopify IMMEDIATELY
            if push_ai_product_to_shopify(ai_product.id):
                pushed_counter.increment()
                logger.info(f"[AI Job {ai_job_id}] ✅ Pushed product to Shopify")

                # Update AI job progress
                with app.app_context():
                    ai_job = AIJob.query.get(ai_job_id)
                    if ai_job:
                        ai_job.ai_products_created = created_counter.get()
                        ai_job.products_pushed = pushed_counter.get()
                        db.session.commit()

                return (True, None)
            else:
                logger.error(f"[AI Job {ai_job_id}] ❌ Failed to push product to Shopify")
                return (False, "Failed to push to Shopify")

        except Exception as e:
            error_msg = f"Error processing product {source_product.id}: {str(e)}"
            logger.error(f"[AI Job {ai_job_id}] {error_msg}", exc_info=True)
            db.session.rollback()
            return (False, error_msg)


def process_ai_job_async(ai_job_id, fast_mode=False, product_limit=None):
    """Process an AI job in the background - create AI dupes for all products from scrape job

    Args:
        ai_job_id: The AI job ID to process
        fast_mode: If True, skip AI image generation and use placeholders (MUCH faster)
        product_limit: Optional limit on number of products to process (for testing)
    """
    with app.app_context():
        try:
            # Get AI job
            ai_job = AIJob.query.get(ai_job_id)
            if not ai_job:
                logger.error(f"AI Job {ai_job_id} not found")
                return

            mode_msg = f"⚡ FAST MODE - Sequential" if fast_mode else f"🎨 PRO MODE - Parallel ({PARALLEL_WORKERS} workers)"
            logger.info(f"[AI Job {ai_job_id}] Starting AI processing - {mode_msg}")

            # Update status to running
            ai_job.status = 'running'
            db.session.commit()

            # Get all products from source scrape job
            source_job = ScrapeJob.query.get(ai_job.source_job_id)
            if not source_job:
                logger.error(f"[AI Job {ai_job_id}] Source job not found")
                ai_job.status = 'error'
                ai_job.error_message = 'Source scrape job not found'
                db.session.commit()
                return

            # Get products (with optional limit for testing)
            query = Product.query.filter_by(job_id=source_job.id)
            if product_limit:
                query = query.limit(product_limit)
            products = query.all()

            limit_msg = f" (limited to {product_limit} for testing)" if product_limit else ""
            logger.info(f"[AI Job {ai_job_id}] Found {len(products)} products to process{limit_msg}")

            if not products:
                logger.warning(f"[AI Job {ai_job_id}] No products found in source job")
                ai_job.status = 'completed'
                ai_job.completed_at = datetime.utcnow()
                db.session.commit()
                return

            # Set push status to in_progress at the start
            ai_job.push_status = 'in_progress'
            ai_job.push_started_at = datetime.utcnow()
            db.session.commit()

            # Thread-safe counters
            created_counter = ThreadSafeCounter()
            pushed_counter = ThreadSafeCounter()

            if fast_mode:
                # FAST MODE: Sequential processing (original code)
                for idx, source_product in enumerate(products, 1):
                    success, error = process_single_product(
                        source_product, ai_job_id, fast_mode, created_counter, pushed_counter
                    )
                    logger.info(f"[AI Job {ai_job_id}] Progress: {idx}/{len(products)}")

            else:
                # PRO MODE: Parallel processing with ThreadPoolExecutor
                logger.info(f"[AI Job {ai_job_id}] 🚀 Starting parallel processing with {PARALLEL_WORKERS} workers")

                with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as parallel_executor:
                    # Submit all products for parallel processing
                    future_to_product = {
                        parallel_executor.submit(
                            process_single_product,
                            product,
                            ai_job_id,
                            fast_mode,
                            created_counter,
                            pushed_counter
                        ): product for product in products
                    }

                    # Process results as they complete
                    completed = 0
                    for future in as_completed(future_to_product):
                        completed += 1
                        product = future_to_product[future]
                        try:
                            success, error = future.result()
                            if not success:
                                logger.error(f"[AI Job {ai_job_id}] Failed: {product.title} - {error}")
                        except Exception as e:
                            logger.error(f"[AI Job {ai_job_id}] Exception processing {product.title}: {str(e)}")

                        # Log progress every 10 products
                        if completed % 10 == 0:
                            logger.info(f"[AI Job {ai_job_id}] Progress: {completed}/{len(products)} products completed")

            # Update AI job - mark both creation and push as completed
            ai_job.ai_products_created = created_counter.get()
            ai_job.products_pushed = pushed_counter.get()
            ai_job.status = 'completed'
            ai_job.push_status = 'completed'
            ai_job.completed_at = datetime.utcnow()
            ai_job.push_completed_at = datetime.utcnow()
            db.session.commit()

            logger.info(f"[AI Job {ai_job_id}] ✅ Completed! Created {created_counter.get()}/{len(products)} AI products and pushed {pushed_counter.get()}/{len(products)} to Shopify")

        except Exception as e:
            logger.error(f"[AI Job {ai_job_id}] Error: {str(e)}", exc_info=True)
            try:
                ai_job = AIJob.query.get(ai_job_id)
                if ai_job:
                    ai_job.status = 'error'
                    ai_job.error_message = str(e)
                    ai_job.completed_at = datetime.utcnow()
                    db.session.commit()
            except:
                pass


def push_products_async(product_ids):
    """Push products to Shopify asynchronously with progress tracking"""
    global push_progress

    with app.app_context():
        success_count = 0

        for idx, product_id in enumerate(product_ids, 1):
            # Check if cancellation was requested
            if push_progress.get('cancel_requested', False):
                push_progress['status'] = 'cancelled'
                push_progress['message'] = f'Cancelled after pushing {success_count}/{len(product_ids)} products'
                push_progress['cancel_requested'] = False
                logger.info(f"Push cancelled: {success_count}/{len(product_ids)} products pushed")
                return

            try:
                push_progress['current'] = idx
                push_progress['message'] = f'Pushing product {idx}/{len(product_ids)}...'

                if push_product_to_shopify(product_id):
                    success_count += 1

            except Exception as e:
                logger.error(f"Error pushing product {product_id}: {str(e)}")
                continue

        push_progress['status'] = 'completed'
        push_progress['message'] = f'Completed! Pushed {success_count}/{len(product_ids)} products to Shopify'
        push_progress['cancel_requested'] = False
        logger.info(f"Push completed: {success_count}/{len(product_ids)} products")


def push_ai_products_async(ai_product_ids):
    """Push AI products to Shopify asynchronously with progress tracking (Legacy - without AI Job tracking)"""
    global ai_push_progress

    with app.app_context():
        success_count = 0

        for idx, ai_product_id in enumerate(ai_product_ids, 1):
            # Check if cancellation was requested
            if ai_push_progress.get('cancel_requested', False):
                ai_push_progress['status'] = 'cancelled'
                ai_push_progress['message'] = f'Cancelled after pushing {success_count}/{len(ai_product_ids)} AI products'
                ai_push_progress['cancel_requested'] = False
                logger.info(f"AI push cancelled: {success_count}/{len(ai_product_ids)} AI products pushed")
                return

            try:
                ai_push_progress['current'] = idx
                ai_push_progress['message'] = f'Pushing AI product {idx}/{len(ai_product_ids)}...'

                if push_ai_product_to_shopify(ai_product_id):
                    success_count += 1

            except Exception as e:
                logger.error(f"Error pushing AI product {ai_product_id}: {str(e)}")
                continue

        ai_push_progress['status'] = 'completed'
        ai_push_progress['message'] = f'Completed! Pushed {success_count}/{len(ai_product_ids)} AI products to Shopify'
        ai_push_progress['cancel_requested'] = False
        logger.info(f"AI push completed: {success_count}/{len(ai_product_ids)} AI products")


def push_ai_products_async_with_job(ai_product_ids, ai_job_id):
    """
    Push AI products to Shopify with AIJob tracking (resume-able, server restart safe)
    """
    global ai_push_progress

    with app.app_context():
        try:
            # Update AIJob push_status to 'in_progress'
            if ai_job_id:
                ai_job = AIJob.query.get(ai_job_id)
                if ai_job:
                    ai_job.push_status = 'in_progress'
                    ai_job.push_started_at = datetime.utcnow()
                    db.session.commit()
                    logger.info(f"[AI Job {ai_job_id}] Starting push to Shopify")

            # Filter products: only push those without shopify_product_id (resume-able)
            products_to_push = []
            for ai_product_id in ai_product_ids:
                ai_product = AIProduct.query.get(ai_product_id)
                if ai_product and not ai_product.shopify_product_id:
                    products_to_push.append(ai_product_id)

            logger.info(f"[AI Job {ai_job_id}] Total products: {len(ai_product_ids)}, Remaining to push: {len(products_to_push)}")

            # Update progress tracking
            ai_push_progress['total'] = len(products_to_push)
            ai_push_progress['already_pushed'] = len(ai_product_ids) - len(products_to_push)

            success_count = 0

            for idx, ai_product_id in enumerate(products_to_push, 1):
                # Check if cancellation was requested
                if ai_push_progress.get('cancel_requested', False):
                    ai_push_progress['status'] = 'cancelled'
                    ai_push_progress['message'] = f'Cancelled after pushing {success_count}/{len(products_to_push)} AI products'
                    ai_push_progress['cancel_requested'] = False
                    logger.info(f"[AI Job {ai_job_id}] Push cancelled: {success_count}/{len(products_to_push)} products pushed")

                    # Update AIJob status
                    if ai_job_id:
                        ai_job = AIJob.query.get(ai_job_id)
                        if ai_job:
                            ai_job.push_status = 'cancelled'
                            db.session.commit()
                    return

                try:
                    ai_push_progress['current'] = idx
                    ai_push_progress['message'] = f'Pushing AI product {idx}/{len(products_to_push)}...'

                    if push_ai_product_to_shopify(ai_product_id):
                        success_count += 1

                        # Update AIJob products_pushed counter (query fresh from database)
                        if ai_job_id:
                            ai_job = AIJob.query.get(ai_job_id)
                            if ai_job:
                                # Count actual pushed products from database
                                pushed_count = AIProduct.query.filter_by(
                                    ai_job_id=ai_job_id
                                ).filter(
                                    AIProduct.shopify_product_id.isnot(None)
                                ).count()
                                ai_job.products_pushed = pushed_count
                                db.session.commit()

                except Exception as e:
                    logger.error(f"[AI Job {ai_job_id}] Error pushing AI product {ai_product_id}: {str(e)}")
                    continue

            # Mark push as completed
            ai_push_progress['status'] = 'completed'
            ai_push_progress['message'] = f'Completed! Pushed {success_count}/{len(products_to_push)} AI products to Shopify'
            ai_push_progress['cancel_requested'] = False

            # Update AIJob status
            if ai_job_id:
                ai_job = AIJob.query.get(ai_job_id)
                if ai_job:
                    ai_job.push_status = 'completed'
                    ai_job.push_completed_at = datetime.utcnow()
                    # Final count from database
                    pushed_count = AIProduct.query.filter_by(
                        ai_job_id=ai_job_id
                    ).filter(
                        AIProduct.shopify_product_id.isnot(None)
                    ).count()
                    ai_job.products_pushed = pushed_count
                    db.session.commit()

            logger.info(f"[AI Job {ai_job_id}] Push completed: {success_count}/{len(products_to_push)} products pushed")

        except Exception as e:
            logger.error(f"[AI Job {ai_job_id}] Error in push_ai_products_async_with_job: {str(e)}", exc_info=True)
            ai_push_progress['status'] = 'error'
            ai_push_progress['message'] = f'Error: {str(e)}'

            # Update AIJob status
            if ai_job_id:
                try:
                    ai_job = AIJob.query.get(ai_job_id)
                    if ai_job:
                        ai_job.push_status = 'error'
                        ai_job.error_message = str(e)
                        db.session.commit()
                except:
                    pass


def push_ai_product_to_shopify(ai_product_id):
    """Push a single AI product from database to Shopify"""
    try:
        ai_product = AIProduct.query.get(ai_product_id)
        if not ai_product:
            logger.error(f"AI Product {ai_product_id} not found")
            return False

        # Check if AI product has already been pushed to Shopify (local database check)
        if ai_product.shopify_product_id:
            logger.warning(f"AI Product {ai_product_id} ({ai_product.title}) has already been pushed to Shopify (ID: {ai_product.shopify_product_id}). Skipping.")
            return True

        logger.info(f"Pushing AI product to Shopify: {ai_product.title}")

        # Convert to Shopify format
        shopify_data = ai_product.to_shopify_format()

        # Log variant information with UK currency context
        variants_count = len(shopify_data.get('variants', []))
        logger.info(f"📦 AI Product has {variants_count} variant(s) ready to push to Shopify (UK Store - GBP £)")
        for idx, variant in enumerate(shopify_data.get('variants', []), 1):
            logger.info(f"  💷 Variant {idx}: {variant.get('title')} - Price: £{variant.get('price')} GBP")

        # AI products already have enhanced titles/descriptions
        logger.info(f"AI Product title: {shopify_data['title']}")

        # DUPLICATE CHECK: Check if product with this title already exists in Shopify (rate-limited)
        with shopify_rate_limiter:
            logger.info(f"🛍️ Shopify: Checking for duplicates...")
            existing_products = shopify_service.find_products_by_title(shopify_data['title'])
            time.sleep(SHOPIFY_DELAY)  # Delay after Shopify call

        if existing_products:
            logger.warning(f"AI Product with title '{shopify_data['title']}' already exists in Shopify. Skipping to prevent duplicate.")
            # Update local database with existing Shopify product ID
            if existing_products[0].get('id'):
                ai_product.status = 'pushed'
                ai_product.shopify_product_id = str(existing_products[0]['id'])
                ai_product.pushed_at = datetime.utcnow()
                db.session.commit()
            return True

        # Create product in Shopify (rate-limited)
        with shopify_rate_limiter:
            logger.info(f"🛍️ Shopify: Creating product...")
            created_product = shopify_service.create_product(shopify_data)
            time.sleep(SHOPIFY_DELAY)  # Delay after Shopify call
            logger.info(f"✅ Shopify: Product created")

        if not created_product:
            logger.error(f"Failed to create AI product in Shopify: {ai_product.title}")
            return False

        shopify_product_id = created_product['id']
        shopify_variants_created = len(created_product.get('variants', []))
        logger.info(f"✅ AI Product created in Shopify with ID: {shopify_product_id}")
        logger.info(f"✅ {shopify_variants_created} variant(s) successfully created in Shopify")

        # Attach images from AI product (rate-limited)
        # Fast Mode: Uses 1 HTTP URL (original image)
        # Pro Mode: Uses 2 base64 data URLs (Nano Banana AI-edited images)
        ai_images = ai_product.images.all()
        if ai_images:
            logger.info(f"Attaching {len(ai_images)} images to Shopify product")
            for ai_image in ai_images:
                with shopify_rate_limiter:
                    logger.info(f"🛍️ Shopify: Uploading image...")
                    success = shopify_service.add_product_image(shopify_product_id, ai_image.image_url)
                    time.sleep(SHOPIFY_DELAY)  # Delay after Shopify call
                    if success:
                        logger.info(f"✅ Shopify: Image uploaded")
        else:
            # Fallback to demo images if no images found
            logger.warning(f"No images found for AI product {ai_product_id}, using demo images")
            demo_images = [
                f"https://dummyimage.com/800x800/FF6B6B/ffffff.png&text=AI+Image+1",
                f"https://dummyimage.com/800x800/4ECDC4/ffffff.png&text=AI+Image+2"
            ]
            for image_url in demo_images:
                with shopify_rate_limiter:
                    success = shopify_service.add_product_image(shopify_product_id, image_url)
                    time.sleep(SHOPIFY_DELAY)  # Delay after Shopify call
                    if success:
                        logger.info(f"Successfully added demo image to product {shopify_product_id}")

        # Disable inventory tracking for all variants (rate-limited)
        for variant in created_product.get('variants', []):
            inventory_item_id = variant.get('inventory_item_id')
            if inventory_item_id:
                with shopify_rate_limiter:
                    logger.info(f"🛍️ Shopify: Disabling inventory tracking...")
                    shopify_service.disable_inventory_tracking(inventory_item_id)
                    time.sleep(SHOPIFY_DELAY)  # Delay after Shopify call

        # Update AI product status in database
        ai_product.status = 'pushed'
        ai_product.shopify_product_id = str(shopify_product_id)
        ai_product.pushed_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Successfully pushed AI product {ai_product_id} to Shopify")
        return True

    except Exception as e:
        logger.error(f"Error pushing AI product {ai_product_id} to Shopify: {str(e)}", exc_info=True)
        return False


def run_workflow_with_context(task_id, url, max_products):
    """Wrapper to run workflow with Flask app context"""
    with app.app_context():
        run_workflow(task_id, url, max_products)


def run_workflow(task_id, url, max_products):
    """
    Main workflow: Start NEW Apify scrape with provided URL and save to database
    STEP 1: Start Apify scrape, wait for completion, get products and save to database
    """
    try:
        logger.info(f"[{task_id}] STEP 1: Starting NEW Apify scrape for URL: {url}")

        # Update job status
        db_service.update_scrape_job(task_id, status='running')

        # START A NEW APIFY SCRAPE with the provided URL
        logger.info(f"[{task_id}] 🚀 Starting Apify scraper for {url}")
        run_id = apify_service.start_scraper(url, max_results=max_products)

        if not run_id:
            logger.error(f"[{task_id}] Failed to start Apify scraper")
            db_service.update_scrape_job(
                task_id,
                status='failed',
                error_message='Failed to start Apify scraper',
                completed_at=datetime.utcnow()
            )
            return

        logger.info(f"[{task_id}] ✅ Apify scraper started - Run ID: {run_id}")
        logger.info(f"[{task_id}] ⏱️  Waiting for Apify to complete scraping...")

        # WAIT for Apify scrape to complete (max 10 minutes timeout)
        success = apify_service.wait_for_completion(run_id, timeout=600, poll_interval=10)

        if not success:
            logger.error(f"[{task_id}] Apify scrape failed or timed out")
            db_service.update_scrape_job(
                task_id,
                status='failed',
                error_message='Apify scrape failed or timed out',
                completed_at=datetime.utcnow()
            )
            return

        logger.info(f"[{task_id}] ✅ Apify scrape completed successfully!")

        # FETCH data from THIS SPECIFIC RUN (not "last run")
        logger.info(f"[{task_id}] 📦 Fetching products from Apify run {run_id}")
        products = apify_service.get_scraped_data(run_id, limit=max_products)

        if not products:
            logger.warning(f"[{task_id}] No products found in Apify run {run_id}")
            db_service.update_scrape_job(
                task_id,
                status='completed',
                total_products=0,
                completed_at=datetime.utcnow()
            )
            return

        logger.info(f"[{task_id}] ✅ Fetched {len(products)} products from Apify run {run_id}")

        # Update total products
        db_service.update_scrape_job(task_id, total_products=len(products))

        # Transform prices (divide by 100, multiply by 2)
        logger.info(f"[{task_id}] Transforming prices")
        products = product_mapper.adjust_prices(products)

        # Process and save each product to database (NO AI enhancement)
        logger.info(f"[{task_id}] Saving products to database")

        job = db_service.get_scrape_job(task_id)

        for idx, product in enumerate(products, 1):
            try:
                logger.info(f"[{task_id}] Processing product {idx}/{len(products)}: {product.get('title', 'Untitled')}")

                # NO OpenAI enhancement - save credits
                # NO Gemini image processing - save credits

                # Map to Shopify format
                shopify_product = product_mapper.map_to_shopify(product)

                # DEBUG: Log what Apify returned and what mapper produced
                logger.info(f"[{task_id}] DEBUG: Apify product has {len(product.get('variants', []))} variants")
                logger.info(f"[{task_id}] DEBUG: Mapper produced {len(shopify_product.get('variants', []))} variants")
                if shopify_product.get('variants'):
                    for v_idx, v in enumerate(shopify_product['variants'][:3], 1):
                        logger.info(f"[{task_id}] DEBUG:   Variant {v_idx}: title='{v.get('title')}', option1='{v.get('option1')}', price='{v.get('price')}'")

                # Extract image URLs (use original images)
                image_urls = image_processor.extract_image_urls(product)

                # If no images, use placeholder
                if not image_urls:
                    image_urls = ['https://via.placeholder.com/500x500?text=Product+Image']

                shopify_product['images'] = image_urls[:2]  # Limit to 2 images

                # Save to database
                saved_product = db_service.save_product(job.id, shopify_product, product)

                if saved_product:
                    db_service.update_scrape_job(task_id, products_processed=idx)
                    logger.info(f"[{task_id}] Saved product {idx} to database")
                else:
                    logger.error(f"[{task_id}] Failed to save product {idx}")

            except Exception as e:
                logger.error(f"[{task_id}] Error processing product {idx}: {str(e)}", exc_info=True)
                continue

        # Mark job as completed
        db_service.update_scrape_job(
            task_id,
            status='completed',
            completed_at=datetime.utcnow()
        )

        logger.info(f"[{task_id}] STEP 1 completed - {len(products)} products saved to database")
        logger.info(f"[{task_id}] STEP 2: Review products and push to Shopify from Products page")

    except Exception as e:
        logger.error(f"[{task_id}] Workflow error: {str(e)}", exc_info=True)
        db_service.update_scrape_job(
            task_id,
            status='failed',
            error_message=str(e),
            completed_at=datetime.utcnow()
        )


def push_product_to_shopify(product_id):
    """
    STEP 2: Push a single product from database to Shopify
    Adds (AI-GENERATED) suffix to product title
    """
    try:
        product = db_service.get_product(product_id)
        if not product:
            logger.error(f"Product {product_id} not found")
            return False

        # Check if product has already been pushed to Shopify (local database check)
        if product.shopify_product_id:
            logger.warning(f"Product {product_id} ({product.title}) has already been pushed to Shopify (ID: {product.shopify_product_id}). Skipping.")
            return True

        logger.info(f"Pushing product to Shopify: {product.title}")

        # Convert to Shopify format
        shopify_data = product.to_shopify_format()

        # Log variant information with UK currency context
        variants_count = len(shopify_data.get('variants', []))
        logger.info(f"📦 Product has {variants_count} variant(s) ready to push to Shopify (UK Store - GBP £)")
        for idx, variant in enumerate(shopify_data.get('variants', []), 1):
            logger.info(f"  💷 Variant {idx}: {variant.get('title')} - Price: £{variant.get('price')} GBP")

        # Add (AI-GENERATED) suffix to title
        original_title = shopify_data.get('title', '')
        if not original_title.endswith('(AI-GENERATED)'):
            shopify_data['title'] = f"{original_title} (AI-GENERATED)"

        logger.info(f"Product title: {shopify_data['title']}")

        # DUPLICATE CHECK: Check if product with this title already exists in Shopify
        existing_products = shopify_service.find_products_by_title(shopify_data['title'])
        if existing_products:
            logger.warning(f"Product with title '{shopify_data['title']}' already exists in Shopify. Skipping to prevent duplicate.")
            # Update local database with existing Shopify product ID
            if existing_products[0].get('id'):
                db_service.update_product_status(product_id, 'pushed', str(existing_products[0]['id']))
            return True

        # Create product in Shopify
        created_product = shopify_service.create_product(shopify_data)

        if not created_product:
            logger.error(f"Failed to create product in Shopify: {product.title}")
            return False

        shopify_product_id = created_product['id']
        shopify_variants_created = len(created_product.get('variants', []))
        logger.info(f"✅ Product created in Shopify with ID: {shopify_product_id}")
        logger.info(f"✅ {shopify_variants_created} variant(s) successfully created in Shopify")

        # Attach 2 demo images (will be replaced by Gemini-generated images later)
        # TODO: Replace with Gemini-generated images
        # Using dummyimage.com which provides direct image URLs that Shopify can process
        demo_images = [
            f"https://dummyimage.com/800x800/4A90E2/ffffff.png&text=Product+Image+1",
            f"https://dummyimage.com/800x800/7B68EE/ffffff.png&text=Product+Image+2"
        ]

        for image_url in demo_images:
            success = shopify_service.add_product_image(shopify_product_id, image_url)
            if success:
                logger.info(f"Successfully added image to product {shopify_product_id}")
            time.sleep(0.5)  # Small delay between image uploads

        # Disable inventory tracking for all variants
        for variant in created_product.get('variants', []):
            inventory_item_id = variant.get('inventory_item_id')
            if inventory_item_id:
                shopify_service.disable_inventory_tracking(inventory_item_id)

        # Update product status in database
        db_service.update_product_status(product_id, 'pushed', str(shopify_product_id))

        # Increment pushed count
        job_id = product.job_id
        if job_id:
            job = ScrapeJob.query.get(job_id)
            if job:
                job.products_pushed = (job.products_pushed or 0) + 1
                db.session.commit()

        logger.info(f"Successfully pushed product {product_id} to Shopify with (AI-GENERATED) suffix")
        return True

    except Exception as e:
        logger.error(f"Error pushing product {product_id} to Shopify: {str(e)}", exc_info=True)
        return False


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    logger.info(f"Starting Flask application on port {port}")
    logger.info(f"Parallel processing workers for Pro Mode: {PARALLEL_WORKERS}")
    logger.info(f"🛡️ Rate Limiting Enabled:")
    logger.info(f"  - Gemini: Max 2 concurrent calls, {GEMINI_DELAY}s delay")
    logger.info(f"  - OpenAI: Max 2 concurrent calls, {OPENAI_DELAY}s delay")
    logger.info(f"  - Shopify: Max 1 concurrent call, {SHOPIFY_DELAY}s delay")
    app.run(host='0.0.0.0', port=port, debug=debug)
