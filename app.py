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
from services.gemini_service import GeminiService, GeminiQuotaExhaustedError
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
# For Railway: Use volume-mounted path (/data) to persist database across deployments
# For local: Falls back to local path
DATABASE_PATH = os.getenv('DATABASE_PATH', '/data/shopify_automation.db')
if not os.path.exists(os.path.dirname(DATABASE_PATH)) and os.path.dirname(DATABASE_PATH) != '':
    # If /data doesn't exist (local dev), use current directory
    DATABASE_PATH = 'shopify_automation.db'
    logger.info(f"📁 Using local database path: {DATABASE_PATH}")
else:
    logger.info(f"📁 Using Railway volume database path: {DATABASE_PATH}")

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', f'sqlite:///{DATABASE_PATH}?timeout=30')
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

# Thread pool for async operations (increased to support 5-6 parallel stores)
executor = ThreadPoolExecutor(max_workers=8)

# Parallel processing executor (configurable workers for Pro Mode)
# Increased to 4 workers with 10 Gemini keys for faster parallel processing
PARALLEL_WORKERS = int(os.getenv('PARALLEL_WORKERS', 4))

# ==================== GLOBAL RATE LIMITERS ====================
# These ensure we never hit API rate limits for Gemini, OpenAI, or Shopify
# Semaphores limit concurrent API calls across all parallel workers

# Gemini Rate Limiter: With 10 API keys, allow 10 concurrent calls for maximum speed
gemini_rate_limiter = threading.Semaphore(10)
GEMINI_DELAY = float(os.getenv('GEMINI_DELAY', 0.3))  # Reduced delay for faster processing with 10 keys

# OpenAI Rate Limiter: Increased for parallel processing across multiple stores
openai_rate_limiter = threading.Semaphore(6)
OPENAI_DELAY = float(os.getenv('OPENAI_DELAY', 0.3))  # Reduced delay for faster processing

# Shopify Rate Limiter: PER-STORE rate limiting (each store has independent 2 req/sec limit)
# Dictionary to store rate limiters per Shopify store URL
shopify_rate_limiters = {}
shopify_rate_limiter_lock = threading.Lock()
SHOPIFY_DELAY = float(os.getenv('SHOPIFY_DELAY', 0.6))  # 0.6 second delay after each Shopify call (under 2/sec)

def get_shopify_rate_limiter(shop_url):
    """Get or create a rate limiter for a specific Shopify store"""
    with shopify_rate_limiter_lock:
        if shop_url not in shopify_rate_limiters:
            # Each store gets its own semaphore (max 1 concurrent call per store)
            shopify_rate_limiters[shop_url] = threading.Semaphore(1)
        return shopify_rate_limiters[shop_url]

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
                # NO FALLBACKS - If Gemini fails, skip this product
                logger.info(f"Editing images with Nano Banana 🍌...")
                ai_image_urls = []
                image_prompt = ""

                # Get ALL images from source product for better context
                all_images = source_product.images.all()
                if not all_images or len(all_images) == 0:
                    logger.error(f"❌ No source images found for product {product_id} - SKIPPING (no fallback allowed)")
                    errors.append(f"Product {product_id}: No source images available")
                    continue

                # Collect all image URLs for context
                all_image_urls = [img.original_url for img in all_images if img.original_url]
                if not all_image_urls:
                    logger.error(f"❌ No valid image URLs for product {product_id} - SKIPPING")
                    errors.append(f"Product {product_id}: No valid image URLs")
                    continue

                # Use first image as primary, but pass all images for context
                primary_image_url = all_image_urls[0]
                logger.info(f"📸 Found {len(all_image_urls)} image(s) for product - using all for context")

                # Image 1: Product in use (clean, no workers/hands/tools) - with auto-retry
                logger.info(f"Editing Image 1 with Nano Banana: Product in use (clean, no workers)...")
                edited_url_1 = None
                max_retries = 3

                for attempt in range(max_retries):
                    try:
                        edited_url_1 = gemini_service.edit_product_image(
                            primary_image_url,
                            source_product.title,
                            variation="product_in_use",
                            all_image_urls=all_image_urls  # Pass all images for context
                        )

                        if edited_url_1:
                            break  # Success
                        else:
                            # Single key exhausted, retry with next key
                            if attempt < max_retries - 1:
                                logger.info(f"🔄 Retrying image 1/2 with next API key (attempt {attempt + 2}/{max_retries})...")
                                time.sleep(1)

                    except GeminiQuotaExhaustedError:
                        # ALL keys exhausted - stop processing and wait
                        logger.error(f"❌ ALL API keys exhausted at product {product_id}")
                        raise  # Propagate to trigger wait logic

                if not edited_url_1:
                    logger.error(f"❌ Gemini edit failed for image 1/2 on product {product_id} after retries - SKIPPING")
                    errors.append(f"Product {product_id}: Gemini image editing failed (image 1/2 - product in use)")
                    continue

                ai_image_urls.append(edited_url_1)
                logger.info(f"✅ Nano Banana: Edited image 1/2 (Product in use - clean)")

                # Image 2: Smart selection between Installation vs Application
                # Detect product category to choose appropriate second image type
                product_lower = source_product.title.lower()

                # Products that need APPLICATION scene (hands applying/using)
                is_application_product = any(keyword in product_lower for keyword in [
                    'marker', 'tape', 'paint', 'spray', 'coating', 'label', 'sticker',
                    'sign', 'decal', 'adhesive', 'line', 'stripe', 'mat', 'carpet',
                    'floor marking', 'road marking', 'safety marking', 'hazard tape',
                    'warning tape', 'barrier tape', 'floor tape', 'duct tape',
                    'reflective tape', 'anti-slip', 'grip tape', 'edge protection',
                    'corner guard', 'foam', 'padding', 'strip', 'seal', 'gasket',
                    'small', 'mini', 'compact', 'portable', 'handheld', 'accessory'
                ])

                # Products that need INSTALLATION scene (workers with tools)
                is_installation_product = any(keyword in product_lower for keyword in [
                    'bollard', 'barrier', 'post', 'pole', 'column', 'fence', 'gate',
                    'wheel stop', 'parking block', 'speed bump', 'hump', 'ramp',
                    'rack', 'stand', 'mounting', 'bracket', 'anchor', 'fixed',
                    'permanent', 'heavy duty', 'industrial', 'commercial',
                    'installation', 'assembly required', 'bolt', 'concrete'
                ])

                # Choose variation based on product type
                if is_application_product and not is_installation_product:
                    second_image_variation = "application"
                    logger.info(f"🎯 Detected application product - using hands-on application scene")
                else:
                    second_image_variation = "installation"
                    logger.info(f"🎯 Detected installation product - using workers installation scene")

                # Image 2: Context-appropriate second image - with auto-retry
                logger.info(f"Editing Image 2 with Nano Banana: {second_image_variation} scene...")
                edited_url_2 = None

                for attempt in range(max_retries):
                    try:
                        edited_url_2 = gemini_service.edit_product_image(
                            primary_image_url,
                            source_product.title,
                            variation=second_image_variation,
                            all_image_urls=all_image_urls  # Pass all images for context
                        )

                        if edited_url_2:
                            break  # Success
                        else:
                            # Single key exhausted, retry with next key
                            if attempt < max_retries - 1:
                                logger.info(f"🔄 Retrying image 2/2 with next API key (attempt {attempt + 2}/{max_retries})...")
                                time.sleep(1)

                    except GeminiQuotaExhaustedError:
                        # ALL keys exhausted - stop processing and wait
                        logger.error(f"❌ ALL API keys exhausted at product {product_id}")
                        raise  # Propagate to trigger wait logic

                if not edited_url_2:
                    logger.error(f"❌ Gemini edit failed for image 2/2 on product {product_id} after retries - SKIPPING")
                    errors.append(f"Product {product_id}: Gemini image editing failed (image 2/2 - {second_image_variation})")
                    continue

                ai_image_urls.append(edited_url_2)
                variation_name = "Application scene" if second_image_variation == "application" else "Installation scene"
                logger.info(f"✅ Nano Banana: Edited image 2/2 ({variation_name})")

                image_prompt = f"Nano Banana edited variations of {source_product.title}"

                # Get source URL from scrape job
                source_url = None
                if source_product.scrape_job:
                    source_url = source_product.scrape_job.source_url

                # Add TWO tags: 1) Source website name, 2) Collection name (product_type)
                tags_list = []

                # Tag 1: Source website name
                if source_url:
                    readable_tag = url_to_readable_tag(source_url)
                    if readable_tag:
                        tags_list.append(readable_tag)

                # Tag 2: Collection name (product_type from scraper)
                if source_product.product_type and source_product.product_type.strip():
                    collection_tag = source_product.product_type.strip()

                    # Skip if collection name is too generic or empty
                    skip_generic = ['product', 'products', 'item', 'items', 'default']
                    if collection_tag.lower() in skip_generic:
                        logger.info(f"Skipping generic collection tag: '{collection_tag}'")
                    else:
                        # Clean up collection tag (capitalize properly)
                        collection_tag = ' '.join(word.capitalize() for word in collection_tag.split())
                        if collection_tag and collection_tag not in tags_list:
                            tags_list.append(collection_tag)
                            logger.info(f"Added collection tag: '{collection_tag}'")

                combined_tags = ', '.join(tags_list) if tags_list else ''

                # Create AI product with enhanced data
                ai_product = AIProduct(
                    source_product_id=source_product.id,
                    title=enhanced_product.get('title', source_product.title),
                    handle=enhanced_product.get('slug', source_product.handle),
                    body_html=enhanced_product.get('body_html', source_product.body_html),
                    product_type=source_product.product_type,
                    tags=combined_tags,
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
                    # FILTER: Skip placeholder variants
                    variant_title_lower = (variant.title or '').lower()
                    variant_option1_lower = (variant.option1 or '').lower()

                    placeholder_keywords = [
                        'please select', 'select option', 'choose', 'select size',
                        'select color', 'select variant'
                    ]

                    is_placeholder = any(keyword in variant_title_lower for keyword in placeholder_keywords) or \
                                   any(keyword in variant_option1_lower for keyword in placeholder_keywords)

                    if is_placeholder:
                        logger.info(f"⏭️  Skipping placeholder variant when creating AI product: {variant.title}")
                        continue

                    # Source products already have doubled prices from adjust_prices()
                    # No need to double again - just copy the price as-is
                    variant_price = float(variant.price) if variant.price else 0

                    # Skip zero-price variants - NO zero-price products allowed
                    if variant_price <= 0.01:
                        logger.warning(f"⏭️  SKIPPING VARIANT: Zero/missing price detected")
                        logger.warning(f"     Product: {source_product.title}")
                        logger.warning(f"     Variant: {variant.title} (Price: £{variant_price})")
                        logger.warning(f"     Product ID: {source_product.id} | Variant ID: {variant.id}")
                        logger.warning(f"     → Fix price in source product or check scraper")
                        continue

                    variant_compare_price = float(variant.compare_at_price) if variant.compare_at_price else None

                    # CRITICAL FIX: Parse variant title to extract option values
                    # Many source products have option1='Default' because they were scraped before the fix
                    # Parse title like "Galvanised / Bolt Down (flanged) excluding Bolts" into distinct options
                    option1_value = variant.option1 if variant.option1 and variant.option1 not in ['Default', 'Default Title'] else None
                    option2_value = variant.option2
                    option3_value = variant.option3

                    # If no valid option1, parse from title
                    if not option1_value and variant.title and variant.title not in ['Default', 'Default Title']:
                        title_parts = variant.title.split('/')
                        title_parts = [part.strip() for part in title_parts if part.strip()]

                        if len(title_parts) >= 1:
                            option1_value = title_parts[0]
                        if len(title_parts) >= 2:
                            option2_value = title_parts[1]
                        if len(title_parts) >= 3:
                            option3_value = title_parts[2]

                    # Final fallback: Leave as None for single-variant products
                    # This prevents "Option 1: Default" from showing in Shopify
                    if not option1_value:
                        option1_value = None

                    ai_variant = AIProductVariant(
                        ai_product_id=ai_product.id,
                        title=variant.title or 'Default Title',
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

                # Check if any variants were created
                # If all variants were skipped (zero price or placeholders), skip entire product
                variant_count = AIProductVariant.query.filter_by(ai_product_id=ai_product.id).count()
                if variant_count == 0:
                    logger.error(f"❌ SKIPPING ENTIRE PRODUCT: No valid variants (all had zero/missing price or were placeholders)")
                    logger.error(f"     Product: {source_product.title} (ID: {source_product.id})")
                    logger.error(f"     → Fix source product prices before creating AI dupes")
                    db.session.rollback()
                    errors.append(f"Product {product_id}: No valid variants (all zero-price or placeholders)")
                    continue

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
        product_limit = data.get('product_limit')  # NEW: Limit number of products to process
        product_offset = data.get('product_offset', 0)  # NEW: Skip first N products

        # Custom Shopify credentials (optional)
        custom_shopify_url = data.get('custom_shopify_url')
        custom_access_token = data.get('custom_access_token')

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
            products_pushed=0,
            custom_shopify_url=custom_shopify_url,
            custom_access_token=custom_access_token
        )
        db.session.add(ai_job)
        db.session.commit()

        # Log if using custom credentials
        if custom_shopify_url:
            logger.info(f"AI job {ai_job.id} will use CUSTOM Shopify store: {custom_shopify_url}")

        logger.info(f"Created AI job {ai_job.id} for scrape job {job_id} (PRO MODE, product_limit={product_limit}, product_offset={product_offset})")

        # Start AI processing in background (always Pro Mode with AI images)
        executor.submit(process_ai_job_async, ai_job.id, False, product_limit, product_offset)

        limit_message = f" - Testing with {product_limit} products" if product_limit else ""
        skip_message = f" - Skipping first {product_offset} products" if product_offset else ""
        return jsonify({
            'message': f'AI job created successfully for scrape job {job_id} (PRO MODE - {PARALLEL_WORKERS} parallel workers){limit_message}{skip_message}',
            'ai_job_id': ai_job.id,
            'status': 'started',
            'product_limit': product_limit,
            'product_offset': product_offset
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

        # Start AI processing in background (will skip already-processed products)
        # Always use Pro Mode (fast_mode=False)
        executor.submit(process_ai_job_async, ai_job_id, False, None)

        return jsonify({
            'message': f'AI job {ai_job_id} resumed successfully (PRO MODE)',
            'ai_job_id': ai_job_id,
            'status': 'started',
            'already_processed': processed_count,
            'remaining': remaining,
            'mode': 'PRO MODE'
        })

    except Exception as e:
        logger.error(f"Error resuming AI job: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/stop-ai-job/<int:ai_job_id>', methods=['POST'])
@login_required
def stop_ai_job(ai_job_id):
    """Stop a running AI job"""
    try:
        # Get the AI job
        ai_job = AIJob.query.get(ai_job_id)
        if not ai_job:
            return jsonify({'error': 'AI job not found'}), 404

        # Check if job is running
        if ai_job.status != 'running':
            return jsonify({'error': f'Job is not running (current status: {ai_job.status})'}), 400

        # Get counts
        processed_count = AIProduct.query.filter_by(ai_job_id=ai_job_id).count()
        source_job = ScrapeJob.query.get(ai_job.source_job_id)
        total_products = Product.query.filter_by(job_id=source_job.id).count() if source_job else 0
        remaining = total_products - processed_count

        logger.info(f"Stopping AI job {ai_job_id}: {processed_count} processed, {remaining} remaining")

        # Update job status to stopped
        ai_job.status = 'stopped'
        ai_job.error_message = 'Manually stopped by user'
        db.session.commit()

        # Note: The background thread will check the status and stop processing
        # at the next opportunity (between products)

        return jsonify({
            'message': f'AI job {ai_job_id} stopped successfully',
            'ai_job_id': ai_job_id,
            'status': 'stopped',
            'products_processed': processed_count,
            'products_remaining': remaining
        })

    except Exception as e:
        logger.error(f"Error stopping AI job: {str(e)}", exc_info=True)
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


# Global progress tracking for fixing Shopify products
fix_shopify_progress = {
    'total': 0,
    'current': 0,
    'status': 'idle',  # idle, running, completed, error, cancelled
    'message': '',
    'cancel_requested': False,
    'updated_count': 0
}


@app.route('/api/fix-shopify-products', methods=['POST'])
@login_required
def fix_shopify_products():
    """Fix existing Shopify products by removing brand names and contact info"""
    try:
        data = request.get_json()
        product_limit = data.get('product_limit', 1000)  # Default 1000 products

        global fix_shopify_progress
        if fix_shopify_progress['status'] == 'running':
            return jsonify({'error': 'Fix operation already in progress'}), 400

        # Reset progress
        fix_shopify_progress = {
            'total': product_limit,
            'current': 0,
            'status': 'running',
            'message': f'Starting to fix {product_limit} products...',
            'cancel_requested': False,
            'updated_count': 0
        }

        # Run in background
        executor.submit(fix_shopify_products_async, product_limit)

        return jsonify({
            'message': f'Started fixing {product_limit} products',
            'status': 'started',
            'total': product_limit
        })

    except Exception as e:
        logger.error(f"Error starting fix operation: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/fix-shopify-progress', methods=['GET'])
@login_required
def get_fix_shopify_progress():
    """Get fix Shopify products progress"""
    return jsonify(fix_shopify_progress)


@app.route('/api/cancel-fix-shopify', methods=['POST'])
@login_required
def cancel_fix_shopify():
    """Cancel ongoing fix Shopify operation"""
    global fix_shopify_progress
    if fix_shopify_progress['status'] == 'running':
        fix_shopify_progress['cancel_requested'] = True
        fix_shopify_progress['message'] = 'Cancellation requested...'
        logger.info("Fix Shopify cancellation requested")
        return jsonify({'message': 'Cancellation requested'})
    else:
        return jsonify({'message': 'No fix operation in progress'})


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'shopify-automation'}), 200


# ==================== HELPER FUNCTIONS ====================

def url_to_readable_tag(url):
    """
    Convert a URL to a readable tag name

    Examples:
        https://streetsolutionsuk.co.uk/ -> "Street Solutions UK"
        https://example.com -> "Example"
        https://my-company.net -> "My Company"

    Args:
        url: The source URL

    Returns:
        str: A readable tag name
    """
    if not url:
        return None

    try:
        import re

        # Remove protocol (http://, https://)
        domain = url.replace('https://', '').replace('http://', '')

        # Remove trailing slash and path
        domain = domain.split('/')[0]

        # Remove www. prefix if present
        domain = domain.replace('www.', '')

        # Remove common TLDs
        for tld in ['.com', '.co.uk', '.net', '.org', '.io', '.uk', '.us', '.ca', '.au', '.de', '.fr']:
            if domain.endswith(tld):
                domain = domain[:-len(tld)]
                break

        # Replace hyphens and underscores with spaces
        domain = domain.replace('-', ' ').replace('_', ' ')

        # Handle country codes at the end (uk, usa, eu, etc.)
        # Check if last word is a short uppercase country/region code
        parts = domain.split()
        if parts and len(parts[-1]) <= 3 and parts[-1].lower() in ['uk', 'usa', 'us', 'eu', 'ca', 'au', 'nz', 'de', 'fr']:
            # Keep it as uppercase
            country_code = parts[-1].upper()
            domain = ' '.join(parts[:-1]) + ' ' + country_code

        # Insert spaces before capital letters in camelCase/PascalCase
        # But only if there are no spaces yet
        if ' ' not in domain:
            # Add space before capital letters (but not at the start)
            domain = re.sub(r'([a-z])([A-Z])', r'\1 \2', domain)
            # Add space before numbers
            domain = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', domain)

        # Capitalize each word
        readable_name = ' '.join(word.capitalize() for word in domain.split())

        return readable_name
    except Exception as e:
        logger.error(f"Error converting URL to tag: {str(e)}")
        return url  # Fallback to original URL


# ==================== WORKFLOW FUNCTIONS ====================

def process_single_product(source_product, ai_job_id, fast_mode, created_counter, pushed_counter, source_url=None):
    """
    Process a single product: Create AI product and push to Shopify
    Thread-safe function for parallel processing

    Args:
        source_product: The source product to process
        ai_job_id: The AI job ID
        fast_mode: If True, skip AI image generation
        created_counter: Thread-safe counter for created products
        pushed_counter: Thread-safe counter for pushed products
        source_url: Optional source website URL to add as a tag

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

            # 🍌 PRO MODE: Edit images with Nano Banana (rate-limited)
            # NO FALLBACKS - If Gemini fails, product creation fails
            first_image = source_product.images.first()
            if not first_image or not first_image.original_url:
                error_msg = "No source image available - cannot create product without images"
                logger.error(f"[AI Job {ai_job_id}] ❌ {error_msg}")
                return (False, error_msg)

            # Edit TWO professional product images (rate-limited with auto-retry)
            # Image 1: Product in use (clean, no workers)
            edited_url_1 = None
            max_retries = 3  # Retry up to 3 times to allow automatic key rotation

            for attempt in range(max_retries):
                try:
                    with gemini_rate_limiter:
                        logger.info(f"[AI Job {ai_job_id}] 🍌 Nano Banana: Editing image 1/2 (Product in use - clean)...")
                        edited_url_1 = gemini_service.edit_product_image(
                            first_image.original_url,
                            source_product.title,
                            variation="product_in_use"
                        )
                        time.sleep(GEMINI_DELAY)  # Delay after Gemini call

                        # If successful (not None), break out of retry loop
                        if edited_url_1:
                            break
                        else:
                            # None means single key exhausted, others available - retry automatically
                            if attempt < max_retries - 1:
                                logger.info(f"[AI Job {ai_job_id}] 🔄 Retrying with next API key (attempt {attempt + 2}/{max_retries})...")
                                time.sleep(1)  # Brief delay before retry

                except GeminiQuotaExhaustedError as e:
                    # ALL keys exhausted - propagate error to trigger wait logic
                    error_msg = f"Gemini quota exhausted: {str(e)}"
                    logger.error(f"[AI Job {ai_job_id}] ❌ {error_msg}")
                    raise  # Re-raise to be caught by process_ai_job_async

            # CRITICAL: If Gemini fails after all retries, STOP - do NOT create product
            if not edited_url_1:
                error_msg = "Gemini image editing failed (image 1/2) after retries - SKIPPING product"
                logger.error(f"[AI Job {ai_job_id}] ❌ {error_msg}")
                return (False, error_msg)

            ai_image_urls.append(edited_url_1)
            logger.info(f"[AI Job {ai_job_id}] ✅ Nano Banana: Image 1/2 edited successfully (Product in use)")

            # Image 2: Installation scene with workers (with auto-retry)
            edited_url_2 = None

            for attempt in range(max_retries):
                try:
                    with gemini_rate_limiter:
                        logger.info(f"[AI Job {ai_job_id}] 🍌 Nano Banana: Editing image 2/2 (Installation scene)...")
                        edited_url_2 = gemini_service.edit_product_image(
                            first_image.original_url,
                            source_product.title,
                            variation="installation"
                        )
                        time.sleep(GEMINI_DELAY)  # Delay after Gemini call

                        # If successful (not None), break out of retry loop
                        if edited_url_2:
                            break
                        else:
                            # None means single key exhausted, others available - retry automatically
                            if attempt < max_retries - 1:
                                logger.info(f"[AI Job {ai_job_id}] 🔄 Retrying with next API key (attempt {attempt + 2}/{max_retries})...")
                                time.sleep(1)  # Brief delay before retry

                except GeminiQuotaExhaustedError as e:
                    # ALL keys exhausted - propagate error to trigger wait logic
                    error_msg = f"Gemini quota exhausted: {str(e)}"
                    logger.error(f"[AI Job {ai_job_id}] ❌ {error_msg}")
                    raise  # Re-raise to be caught by process_ai_job_async

            # CRITICAL: If Gemini fails after all retries, STOP - do NOT create product
            if not edited_url_2:
                error_msg = "Gemini image editing failed (image 2/2) after retries - SKIPPING product"
                logger.error(f"[AI Job {ai_job_id}] ❌ {error_msg}")
                return (False, error_msg)

            ai_image_urls.append(edited_url_2)
            logger.info(f"[AI Job {ai_job_id}] ✅ Nano Banana: Image 2/2 edited successfully (Installation scene)")

            image_prompt = f"Nano Banana edited variations of {source_product.title}"

            # STEP 3: Create AI product in database
            # Add TWO tags: 1) Source website name, 2) Collection name (product_type)
            tags_list = []

            # Tag 1: Source website name
            if source_url:
                readable_tag = url_to_readable_tag(source_url)
                if readable_tag:
                    tags_list.append(readable_tag)

            # Tag 2: Collection name (product_type from scraper)
            if source_product.product_type and source_product.product_type.strip():
                collection_tag = source_product.product_type.strip()

                # Skip if collection name is too generic or empty
                skip_generic = ['product', 'products', 'item', 'items', 'default']
                if collection_tag.lower() in skip_generic:
                    logger.info(f"[AI Job {ai_job_id}] Skipping generic collection tag: '{collection_tag}'")
                else:
                    # Clean up collection tag (capitalize properly)
                    collection_tag = ' '.join(word.capitalize() for word in collection_tag.split())
                    if collection_tag and collection_tag not in tags_list:
                        tags_list.append(collection_tag)
                        logger.info(f"[AI Job {ai_job_id}] Added collection tag: '{collection_tag}'")

            combined_tags = ', '.join(tags_list)

            ai_product = AIProduct(
                source_product_id=source_product.id,
                ai_job_id=ai_job_id,
                title=enhanced_product.get('title', source_product.title),
                handle=enhanced_product.get('slug', source_product.handle),
                body_html=enhanced_product.get('body_html', source_product.body_html),
                product_type=source_product.product_type,
                tags=combined_tags,
                vendor=source_product.vendor,
                option1_name=source_product.option1_name,
                option2_name=source_product.option2_name,
                option3_name=source_product.option3_name,
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
                # FILTER: Skip placeholder variants
                variant_title_lower = (variant.title or '').lower()
                variant_option1_lower = (variant.option1 or '').lower()

                placeholder_keywords = [
                    'please select', 'select option', 'choose', 'select size',
                    'select color', 'select variant'
                ]

                is_placeholder = any(keyword in variant_title_lower for keyword in placeholder_keywords) or \
                               any(keyword in variant_option1_lower for keyword in placeholder_keywords)

                if is_placeholder:
                    logger.info(f"⏭️  Skipping placeholder variant in AI job: {variant.title}")
                    continue

                # Source products already have doubled prices from adjust_prices()
                # No need to double again - just copy the price as-is
                variant_price = float(variant.price) if variant.price else 0

                # Skip zero-price variants - NO zero-price products allowed
                if variant_price <= 0.01:
                    logger.warning(f"⏭️  SKIPPING VARIANT: Zero/missing price detected")
                    logger.warning(f"     Product: {source_product.title}")
                    logger.warning(f"     Variant: {variant.title} (Price: £{variant_price})")
                    logger.warning(f"     Product ID: {source_product.id} | Variant ID: {variant.id}")
                    logger.warning(f"     → Fix price in source product or check scraper")
                    continue

                variant_compare_price = float(variant.compare_at_price) if variant.compare_at_price else None

                # CRITICAL FIX: Parse variant title to extract option values
                # Many source products have option1='Default' because they were scraped before the fix
                # Parse title like "Galvanised / Bolt Down (flanged) excluding Bolts" into distinct options
                option1_value = variant.option1 if variant.option1 and variant.option1 not in ['Default', 'Default Title'] else None
                option2_value = variant.option2
                option3_value = variant.option3

                # If no valid option1, parse from title
                if not option1_value and variant.title and variant.title not in ['Default', 'Default Title']:
                    title_parts = variant.title.split('/')
                    title_parts = [part.strip() for part in title_parts if part.strip()]

                    if len(title_parts) >= 1:
                        option1_value = title_parts[0]
                    if len(title_parts) >= 2:
                        option2_value = title_parts[1]
                    if len(title_parts) >= 3:
                        option3_value = title_parts[2]

                # Final fallback: Leave as None for single-variant products
                # This prevents "Option 1: Default" from showing in Shopify
                if not option1_value:
                    option1_value = None

                ai_variant = AIProductVariant(
                    ai_product_id=ai_product.id,
                    title=variant.title or 'Default Title',
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

            # Check if any variants were created
            # If all variants were skipped (zero price or placeholders), skip entire product
            variant_count = AIProductVariant.query.filter_by(ai_product_id=ai_product.id).count()
            if variant_count == 0:
                logger.error(f"[AI Job {ai_job_id}] ❌ SKIPPING ENTIRE PRODUCT: No valid variants")
                logger.error(f"     Product: {source_product.title} (ID: {source_product.id})")
                logger.error(f"     All variants had zero/missing price or were placeholders")
                logger.error(f"     → Fix source product prices before re-processing")
                db.session.rollback()
                return (False, "No valid variants - all zero-price or placeholders")

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


def process_ai_job_async(ai_job_id, fast_mode=False, product_limit=None, product_offset=0):
    """Process an AI job in the background - create AI dupes for all products from scrape job

    Args:
        ai_job_id: The AI job ID to process
        fast_mode: If True, skip AI image generation and use placeholders (MUCH faster)
        product_limit: Optional limit on number of products to process (for testing)
        product_offset: Skip first N products (useful for continuing from where you left off)
    """
    with app.app_context():
        try:
            # Get AI job
            ai_job = AIJob.query.get(ai_job_id)
            if not ai_job:
                logger.error(f"AI Job {ai_job_id} not found")
                return

            logger.info(f"[AI Job {ai_job_id}] Starting AI processing - 🎨 PRO MODE - Parallel ({PARALLEL_WORKERS} workers)")

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

            # Get products (with optional skip and limit)
            query = Product.query.filter_by(job_id=source_job.id).order_by(Product.id)

            # Skip first N products if offset specified
            if product_offset:
                query = query.offset(product_offset)

            # Limit to N products if specified
            if product_limit:
                query = query.limit(product_limit)

            products = query.all()

            skip_msg = f" (skipped first {product_offset})" if product_offset else ""
            limit_msg = f" (limited to {product_limit})" if product_limit else ""
            logger.info(f"[AI Job {ai_job_id}] Found {len(products)} products to process{skip_msg}{limit_msg}")

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

            # Track products that failed due to quota exhaustion (for retry)
            failed_due_to_quota = []
            quota_exhausted = False

            # PRO MODE: Parallel processing with ThreadPoolExecutor
            logger.info(f"[AI Job {ai_job_id}] 🚀 Starting parallel processing with {PARALLEL_WORKERS} workers")

            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as parallel_executor:
                # Submit all products for parallel processing
                future_to_product = {
                    parallel_executor.submit(
                        process_single_product,
                        product,
                        ai_job_id,
                        False,  # Always Pro Mode
                        created_counter,
                        pushed_counter,
                        source_job.source_url
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
                    except GeminiQuotaExhaustedError as e:
                        # Quota exhausted - cancel remaining tasks
                        logger.error(f"[AI Job {ai_job_id}] ⚠️ QUOTA EXHAUSTED at product {completed}/{len(products)}")
                        logger.error(f"   Error: {str(e)}")
                        quota_exhausted = True
                        # Track this product and any remaining products for retry
                        failed_due_to_quota.append(product)
                        # Note: ThreadPoolExecutor will finish running tasks, we just track failures
                    except Exception as e:
                        logger.error(f"[AI Job {ai_job_id}] Exception processing {product.title}: {str(e)}")

                    # Log progress every 10 products
                    if completed % 10 == 0:
                        logger.info(f"[AI Job {ai_job_id}] Progress: {completed}/{len(products)} products completed")

                    # Check if job was stopped by user
                    db.session.refresh(ai_job)
                    if ai_job.status == 'stopped':
                        logger.info(f"[AI Job {ai_job_id}] ⏹️ Job stopped by user at {completed}/{len(products)} products")
                        # Cancel remaining futures
                        for fut, prod in future_to_product.items():
                            if fut != future and not fut.done():
                                fut.cancel()
                        break  # Exit the loop

                    # If quota exhausted, track remaining products in queue as failed
                    if quota_exhausted:
                        # All remaining products that haven't been processed yet
                        for fut, prod in future_to_product.items():
                            if fut != future and not fut.done():
                                failed_due_to_quota.append(prod)
                        break  # Exit the loop early

            # If quota was exhausted, wait until midnight Pacific and retry failed products
            if quota_exhausted and failed_due_to_quota:
                logger.info(f"[AI Job {ai_job_id}] ⚠️ QUOTA EXHAUSTED - {len(failed_due_to_quota)} products remaining")
                logger.info(f"[AI Job {ai_job_id}] 💤 Waiting until midnight Pacific Time for quota reset...")

                # Update AI job status to indicate we're waiting for quota reset
                ai_job.status = 'waiting_for_quota_reset'
                ai_job.ai_products_created = created_counter.get()
                ai_job.products_pushed = pushed_counter.get()
                ai_job.error_message = f'Quota exhausted. Waiting for reset. {len(failed_due_to_quota)} products remaining.'
                db.session.commit()

                # Calculate time until midnight Pacific
                seconds_until_reset, reset_time = gemini_service._calculate_quota_reset_time()
                hours_until_reset = seconds_until_reset / 3600

                logger.info(f"[AI Job {ai_job_id}] ⏰ Quota resets at: {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                logger.info(f"[AI Job {ai_job_id}] ⏰ Sleeping for {hours_until_reset:.2f} hours...")

                # Sleep until quota reset (+ 60 seconds buffer to ensure quota has reset)
                time.sleep(seconds_until_reset + 60)

                logger.info(f"[AI Job {ai_job_id}] ✅ Quota should have reset! Resuming processing...")

                # Reset quota exhaustion flags
                gemini_service.reset_quota_flags()

                # Update AI job status to running again
                ai_job.status = 'running'
                ai_job.error_message = f'Resumed after quota reset. Retrying {len(failed_due_to_quota)} products.'
                db.session.commit()

                # RETRY failed products
                logger.info(f"[AI Job {ai_job_id}] 🔄 Retrying {len(failed_due_to_quota)} products that failed due to quota...")

                retry_created = ThreadSafeCounter()
                retry_pushed = ThreadSafeCounter()

                if fast_mode:
                    # FAST MODE: Sequential retry
                    for idx, source_product in enumerate(failed_due_to_quota, 1):
                        try:
                            success, error = process_single_product(
                                source_product, ai_job_id, fast_mode, retry_created, retry_pushed, source_job.source_url
                            )
                            logger.info(f"[AI Job {ai_job_id}] Retry Progress: {idx}/{len(failed_due_to_quota)}")
                        except GeminiQuotaExhaustedError as e:
                            # If quota exhausted again, stop and let user know
                            logger.error(f"[AI Job {ai_job_id}] ⚠️ QUOTA EXHAUSTED AGAIN during retry at {idx}/{len(failed_due_to_quota)}")
                            logger.error(f"   You may have too many products for your quota. Consider adding more API keys.")
                            ai_job.status = 'error'
                            ai_job.error_message = f'Quota exhausted again during retry. {len(failed_due_to_quota) - idx} products still pending.'
                            db.session.commit()
                            return

                else:
                    # PRO MODE: Parallel retry
                    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as retry_executor:
                        retry_futures = {
                            retry_executor.submit(
                                process_single_product,
                                product,
                                ai_job_id,
                                fast_mode,
                                retry_created,
                                retry_pushed,
                                source_job.source_url
                            ): product for product in failed_due_to_quota
                        }

                        retry_completed = 0
                        for future in as_completed(retry_futures):
                            retry_completed += 1
                            product = retry_futures[future]
                            try:
                                success, error = future.result()
                                if not success:
                                    logger.error(f"[AI Job {ai_job_id}] Retry failed: {product.title} - {error}")
                            except GeminiQuotaExhaustedError as e:
                                logger.error(f"[AI Job {ai_job_id}] ⚠️ QUOTA EXHAUSTED AGAIN during retry")
                                logger.error(f"   You may have too many products for your quota. Consider adding more API keys.")
                                ai_job.status = 'error'
                                ai_job.error_message = f'Quota exhausted again during retry. Some products still pending.'
                                db.session.commit()
                                return
                            except Exception as e:
                                logger.error(f"[AI Job {ai_job_id}] Exception during retry: {product.title}: {str(e)}")

                # Update counters with retry results
                total_created = created_counter.get() + retry_created.get()
                total_pushed = pushed_counter.get() + retry_pushed.get()

                logger.info(f"[AI Job {ai_job_id}] ✅ Retry complete! Created {retry_created.get()}/{len(failed_due_to_quota)} AI products")
                logger.info(f"[AI Job {ai_job_id}] 📊 Total: {total_created}/{len(products)} created, {total_pushed}/{len(products)} pushed")

                # Update AI job with final counts
                ai_job.ai_products_created = total_created
                ai_job.products_pushed = total_pushed
                ai_job.status = 'completed'
                ai_job.push_status = 'completed'
                ai_job.completed_at = datetime.utcnow()
                ai_job.push_completed_at = datetime.utcnow()
                ai_job.error_message = None
                db.session.commit()

            else:
                # No quota exhaustion - check if all products were processed
                total_created = created_counter.get()
                total_pushed = pushed_counter.get()
                total_products = len(products)

                ai_job.ai_products_created = total_created
                ai_job.products_pushed = total_pushed

                # Calculate success rate
                success_rate = (total_created / total_products * 100) if total_products > 0 else 0

                # Determine status based on success rate
                if total_created == total_products:
                    # 100% success
                    ai_job.status = 'completed'
                    ai_job.push_status = 'completed'
                    ai_job.error_message = None
                    logger.info(f"[AI Job {ai_job_id}] ✅ Completed! Created {total_created}/{total_products} AI products and pushed {total_pushed}/{total_products} to Shopify")
                elif total_created >= total_products * 0.9:
                    # 90%+ success - mark as completed with warning
                    ai_job.status = 'completed'
                    ai_job.push_status = 'completed'
                    failed_count = total_products - total_created
                    ai_job.error_message = f"Completed with {failed_count} failed products ({success_rate:.1f}% success rate)"
                    logger.warning(f"[AI Job {ai_job_id}] ⚠️ Completed with warnings! Created {total_created}/{total_products} ({success_rate:.1f}%), {failed_count} products failed")
                else:
                    # Less than 90% success - mark as partial/error
                    ai_job.status = 'partial'
                    ai_job.push_status = 'partial'
                    failed_count = total_products - total_created
                    ai_job.error_message = f"Partial completion: {failed_count} products failed ({success_rate:.1f}% success rate). Check logs for details."
                    logger.error(f"[AI Job {ai_job_id}] ⚠️ Partial completion! Created {total_created}/{total_products} ({success_rate:.1f}%), {failed_count} products failed")

                ai_job.completed_at = datetime.utcnow()
                ai_job.push_completed_at = datetime.utcnow()
                db.session.commit()

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

        # Get AI job to check for custom Shopify credentials
        ai_job = AIJob.query.get(ai_product.ai_job_id)

        # Use custom Shopify credentials if provided, otherwise use default
        active_shopify_service = shopify_service  # Default
        current_shop_url = shopify_service.shop_url  # Track URL for per-store rate limiting

        if ai_job and ai_job.custom_shopify_url:
            logger.info(f"🔧 Using CUSTOM Shopify store: {ai_job.custom_shopify_url}")
            active_shopify_service = ShopifyService(
                shop_url=ai_job.custom_shopify_url,
                access_token=ai_job.custom_access_token
            )
            current_shop_url = active_shopify_service.shop_url
        else:
            logger.info(f"🔧 Using DEFAULT Shopify store from .env")

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
        with get_shopify_rate_limiter(current_shop_url):
            logger.info(f"🛍️ Shopify: Checking for duplicates...")
            existing_products = active_shopify_service.find_products_by_title(shopify_data['title'])
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
        with get_shopify_rate_limiter(current_shop_url):
            logger.info(f"🛍️ Shopify: Creating product...")
            created_product = active_shopify_service.create_product(shopify_data)
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
        # NO FALLBACKS - If no images, this should never happen (product creation should have failed earlier)
        ai_images = ai_product.images.all()
        if not ai_images:
            logger.error(f"❌ CRITICAL: No images found for AI product {ai_product_id} - This should never happen!")
            logger.error(f"   Product should have been rejected during creation. Deleting from Shopify...")
            # Delete the product from Shopify since it has no images
            active_shopify_service.delete_product(shopify_product_id)
            return False

        logger.info(f"Attaching {len(ai_images)} images to Shopify product")
        for ai_image in ai_images:
            with get_shopify_rate_limiter(current_shop_url):
                logger.info(f"🛍️ Shopify: Uploading image...")
                success = active_shopify_service.add_product_image(shopify_product_id, ai_image.image_url)
                time.sleep(SHOPIFY_DELAY)  # Delay after Shopify call
                if success:
                    logger.info(f"✅ Shopify: Image uploaded")

        # Disable inventory tracking for all variants (rate-limited)
        for variant in created_product.get('variants', []):
            inventory_item_id = variant.get('inventory_item_id')
            if inventory_item_id:
                with get_shopify_rate_limiter(current_shop_url):
                    logger.info(f"🛍️ Shopify: Disabling inventory tracking...")
                    active_shopify_service.disable_inventory_tracking(inventory_item_id)
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

        # WAIT for Apify scrape to complete
        # For large scrapes (80k products): 6 hour timeout, check every 60 seconds
        # Timeout: 21600 seconds = 6 hours (enough for massive scrapes)
        # Poll interval: 60 seconds (reduces API calls from 360 to 6 per hour)
        success = apify_service.wait_for_completion(run_id, timeout=21600, poll_interval=60)

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

        # 🎯 ENRICH WITH SHOPIFY JSON API - Get option names from Shopify's native JSON
        logger.info(f"[{task_id}] 🔍 Enriching products with Shopify JSON API for option names...")
        enriched_count = 0

        for product in products:
            # Get product URL from various possible locations in scraped data
            product_url = (
                product.get('url') or
                product.get('link') or
                product.get('productUrl') or
                product.get('_original', {}).get('url') or
                product.get('_original', {}).get('link')
            )

            if product_url:
                # Fetch full product data from Shopify JSON API
                shopify_json = apify_service.enrich_product_with_shopify_json(product_url)

                if shopify_json and 'options' in shopify_json:
                    # Merge Shopify JSON options into product data
                    product['options'] = shopify_json['options']
                    enriched_count += 1
                    logger.info(f"[{task_id}] ✅ Enriched '{product.get('title', 'Unknown')[:50]}' with {len(shopify_json['options'])} option(s)")

                    # Log option names
                    for opt in shopify_json['options']:
                        opt_name = opt.get('name', 'Unknown')
                        opt_values_count = len(opt.get('values', []))
                        logger.info(f"[{task_id}]    → Option: '{opt_name}' ({opt_values_count} values)")

        logger.info(f"[{task_id}] 📊 Enrichment complete: {enriched_count}/{len(products)} products enriched with option names")

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


def fix_shopify_products_async(product_limit):
    """
    Fix existing Shopify products by removing brand names and contact info
    Fetches latest N products from Shopify and re-processes them through OpenAI
    """
    global fix_shopify_progress

    with app.app_context():
        try:
            logger.info(f"Starting fix operation for {product_limit} products")
            fix_shopify_progress['message'] = f'Fetching {product_limit} products from Shopify...'

            # Fetch products from Shopify in batches (250 max per request)
            all_products = []
            remaining = product_limit
            since_id = None

            while remaining > 0:
                batch_size = min(remaining, 250)
                logger.info(f"Fetching batch of {batch_size} products (since_id={since_id})")

                with get_shopify_rate_limiter(shopify_service.shop_url):
                    products_batch = shopify_service.get_products(limit=batch_size, since_id=since_id)
                    time.sleep(SHOPIFY_DELAY)

                if not products_batch:
                    logger.info(f"No more products to fetch. Total fetched: {len(all_products)}")
                    break

                all_products.extend(products_batch)
                remaining -= len(products_batch)

                # Update since_id for next batch (get last product ID)
                if products_batch:
                    since_id = products_batch[-1]['id']

                logger.info(f"Fetched {len(all_products)}/{product_limit} products so far")

                # If we got less than batch_size, we've reached the end
                if len(products_batch) < batch_size:
                    break

            logger.info(f"Total products fetched: {len(all_products)}")
            fix_shopify_progress['total'] = len(all_products)
            fix_shopify_progress['message'] = f'Processing {len(all_products)} products...'

            updated_count = 0

            # Process each product
            for idx, shopify_product in enumerate(all_products, 1):
                # Check if cancellation was requested
                if fix_shopify_progress.get('cancel_requested', False):
                    fix_shopify_progress['status'] = 'cancelled'
                    fix_shopify_progress['message'] = f'Cancelled after updating {updated_count}/{len(all_products)} products'
                    fix_shopify_progress['cancel_requested'] = False
                    logger.info(f"Fix operation cancelled: {updated_count}/{len(all_products)} products updated")
                    return

                try:
                    fix_shopify_progress['current'] = idx
                    fix_shopify_progress['message'] = f'Processing product {idx}/{len(all_products)}: {shopify_product.get("title", "Untitled")[:50]}...'

                    product_id = shopify_product['id']
                    current_title = shopify_product.get('title', '')
                    current_body_html = shopify_product.get('body_html', '')

                    logger.info(f"[{idx}/{len(all_products)}] Processing: {current_title[:80]}")

                    # Prepare data for OpenAI
                    product_data = {
                        'title': current_title,
                        'description': current_body_html,
                        'body_html': current_body_html,
                        'price': '0.00',
                        'product_type': shopify_product.get('product_type', ''),
                        'vendor': shopify_product.get('vendor', '')
                    }

                    # Re-process through OpenAI to remove brand names and contact info (rate-limited)
                    with openai_rate_limiter:
                        logger.info(f"[{idx}/{len(all_products)}] OpenAI: Cleaning product content...")
                        enhanced_product = openai_service.enhance_product_description(product_data)
                        time.sleep(OPENAI_DELAY)

                    # Extract cleaned fields
                    cleaned_title = enhanced_product.get('title', current_title)
                    cleaned_body_html = enhanced_product.get('body_html', current_body_html)

                    # Check if anything actually changed
                    title_changed = cleaned_title != current_title
                    body_changed = cleaned_body_html != current_body_html

                    if not title_changed and not body_changed:
                        logger.info(f"[{idx}/{len(all_products)}] No changes needed - skipping update")
                        continue

                    # Prepare update payload (only update changed fields)
                    update_data = {}
                    if title_changed:
                        update_data['title'] = cleaned_title
                        logger.info(f"[{idx}/{len(all_products)}] Title cleaned: {current_title[:50]}... -> {cleaned_title[:50]}...")
                    if body_changed:
                        update_data['body_html'] = cleaned_body_html
                        logger.info(f"[{idx}/{len(all_products)}] Description cleaned ({len(current_body_html)} -> {len(cleaned_body_html)} chars)")

                    # Update product in Shopify (rate-limited)
                    with get_shopify_rate_limiter(shopify_service.shop_url):
                        logger.info(f"[{idx}/{len(all_products)}] Shopify: Updating product...")
                        updated = shopify_service.update_product(product_id, update_data)
                        time.sleep(SHOPIFY_DELAY)

                    if updated:
                        updated_count += 1
                        fix_shopify_progress['updated_count'] = updated_count
                        logger.info(f"[{idx}/{len(all_products)}] Product updated successfully (Total: {updated_count} updated)")
                    else:
                        logger.error(f"[{idx}/{len(all_products)}] Failed to update product")

                except Exception as e:
                    logger.error(f"[{idx}/{len(all_products)}] Error processing product: {str(e)}", exc_info=True)
                    continue

            # Mark as completed
            fix_shopify_progress['status'] = 'completed'
            fix_shopify_progress['message'] = f'Completed! Updated {updated_count}/{len(all_products)} products'
            fix_shopify_progress['cancel_requested'] = False
            logger.info(f"Fix operation completed: {updated_count}/{len(all_products)} products updated")

        except Exception as e:
            logger.error(f"Error in fix_shopify_products_async: {str(e)}", exc_info=True)
            fix_shopify_progress['status'] = 'error'
            fix_shopify_progress['message'] = f'Error: {str(e)}'


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
