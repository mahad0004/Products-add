# Shopify Product Automation with AI Enhancement

Complete Flask application for automated Shopify product scraping, AI-powered image editing, and intelligent product management.

## 🚀 Features

### Core Features
✅ **Login System** - Secure single-user authentication (Username: Mahad, Password: Mahad)
✅ **Database Storage** - All products stored in SQLite database (PostgreSQL-ready)
✅ **Product Review** - Review and approve products before pushing to Shopify
✅ **Bulk Actions** - Approve, reject, or push multiple products at once
✅ **Status Tracking** - Track which products have been added to Shopify (✅/❌)
✅ **Modern UI** - Clean, responsive dashboard with dark theme
✅ **Automated Scraping** - Uses Apify to fetch products from last run
✅ **Price Transformation** - Automatic pricing logic (divide by 100, multiply by 2)

### 🤖 AI Enhancement Features
✅ **AI Dupe Jobs** - Create AI-enhanced product versions with two modes:
   - **⚡ Fast Mode**: Quick processing with 1 original image, no AI editing
   - **🎨 Pro Mode**: Full AI enhancement with 2 edited images using Nano Banana

✅ **Nano Banana Image Editing** - Google Gemini 2.5 Flash Image AI editing:
   - Multiple camera angles (front view, 45° angle)
   - Professional lighting variations
   - Removes ALL text, logos, watermarks automatically
   - Creates clean, professional e-commerce images

✅ **OpenAI SEO Enhancement** - AI-powered content generation:
   - Enhanced product titles and descriptions
   - SEO-optimized metadata
   - Professional product copy

✅ **Parallel Processing** - Pro Mode processes multiple products simultaneously:
   - 2 concurrent workers (configurable)
   - Rate-limited to prevent API overload
   - Up to 2x faster than sequential processing

✅ **Resume & Recovery** - Bullet-proof job management:
   - Automatically detects stopped jobs on startup
   - Resume button for interrupted jobs
   - Skips already-processed products
   - No duplicate work or data loss

✅ **Rate Limiting Protection** - Never hit API limits:
   - Gemini: Max 2 concurrent, 1s delay
   - OpenAI: Max 2 concurrent, 0.5s delay
   - Shopify: Max 1 concurrent, 0.6s delay (under 2 req/sec limit)

## Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Flask Configuration
FLASK_DEBUG=False
PORT=5000
SECRET_KEY=your-secret-key-here

# Apify Configuration
APIFY_API_TOKEN=your_apify_token

# Shopify Configuration
SHOPIFY_SHOP_URL=https://your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=your_shopify_token

# OpenAI Configuration (optional for SEO enhancement)
OPENAI_API_KEY=your_openai_key

# Google Gemini (optional for image enhancement)
GOOGLE_API_KEY=your_google_key
```

### 3. Run the Application

```bash
python app.py
```

Open http://localhost:5000 in your browser.

## Usage

### 1. Login

- Navigate to http://localhost:5000
- Username: `Mahad`
- Password: `Mahad`

### 2. Start Scraping

1. Click **"Scrape"** in the navigation
2. Enter the Shopify store URL you want to scrape
3. Set max products (default: 200)
4. Click **"Start Scraping"**

The system will:
- Scrape products using Apify
- Apply price transformations
- (Optional) Enhance with AI-generated SEO content
- Save all products to database

### 3. Review Products

1. Click **"Products"** in the navigation
2. View all scraped products in a table
3. Check the **"Added to Shopify"** column:
   - ✅ = Already pushed to Shopify
   - ❌ = Not yet pushed

### 4. Push Products to Shopify

**Option A: Select Individual Products**
1. Check the boxes next to products you want to push
2. Click **"Push to Shopify"**
3. Confirm the action

**Option B: Approve First, Then Push**
1. Select products
2. Click **"Approve Selected"**
3. Filter by "Approved" status
4. Push approved products to Shopify

### 5. Monitor Dashboard

Click **"Dashboard"** to see:
- Total scrape jobs
- Total products in database
- Pending review count
- Approved products count
- Products pushed to Shopify

## Database Schema

### Tables

**scrape_jobs** - Tracks scraping jobs
- task_id, source_url, status, total_products, products_pushed, etc.

**products** - Stores product details
- title, handle, body_html, product_type, tags, vendor, status, shopify_product_id

**product_variants** - Product variants
- title, sku, price, compare_at_price, option1-3

**product_images** - Product images
- original_url, processed_url, position

**product_metafields** - Product metafields
- namespace, key, value, type

### Product Statuses

- `pending` - Awaiting review
- `approved` - Approved for push
- `rejected` - Rejected
- `pushed` - Successfully pushed to Shopify

## Architecture

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │
       ▼
┌─────────────┐      ┌──────────────┐
│  Flask App  │─────▶│   Database   │
│  (app.py)   │◀─────│   (SQLite)   │
└──────┬──────┘      └──────────────┘
       │
       ├──► ApifyService ──────► Apify API
       │
       ├──► OpenAIService ─────► OpenAI API (optional)
       │
       ├──► ProductMapper ─────► Data transformation
       │
       └──► ShopifyService ────► Shopify Admin API
```

## API Endpoints

### Authentication
- `GET /login` - Login page
- `POST /api/login` - Login handler
- `POST /api/logout` - Logout handler

### Dashboard
- `GET /` - Dashboard
- `GET /api/stats` - Get statistics

### Scraping
- `GET /scrape` - Scraping page
- `POST /api/scrape` - Start scraping job
- `GET /api/jobs` - Get all jobs
- `GET /api/jobs/<task_id>` - Get job status

### Products
- `GET /products` - Products page
- `GET /api/products` - Get products (with filters)
- `GET /api/products/<id>` - Get single product
- `PUT /api/products/<id>` - Update product
- `DELETE /api/products/<id>` - Delete product
- `POST /api/products/bulk-action` - Bulk operations

### Bulk Actions

```json
{
  "action": "approve|reject|delete|push_to_shopify",
  "product_ids": [1, 2, 3, 4]
}
```

## Configuration

### Apify Scraper Settings

The scraper is configured with these defaults:
- **Proxy**: Residential (UK)
- **Max Pages**: 30,000
- **Max Depth**: 7
- **Request Delay**: 1000ms
- **Max Results**: 200 (configurable)
- **Scrapes**: Products, Collections, Variants

### Price Transformation

Products undergo this transformation:
```python
truncated = int(original_price / 100)
new_price = truncated * 2
```

Example: £4999 → £49 → £98

### Shopify Settings

- All products created as `active`
- Inventory tracking disabled by default
- Rate limiting: 0.5s between API calls

## Production Deployment

### Using Gunicorn

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Using Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

```bash
docker build -t shopify-automation .
docker run -p 5000:5000 --env-file .env shopify-automation
```

### Environment Variables for Production

```env
FLASK_DEBUG=False
SECRET_KEY=generate-a-strong-secret-key
DATABASE_URL=postgresql://user:pass@host/db  # For PostgreSQL
```

## Troubleshooting

### Database Issues

**Reset Database:**
```bash
rm shopify_automation.db
python app.py  # Will recreate tables
```

**View Database:**
```bash
sqlite3 shopify_automation.db
.tables
SELECT * FROM products LIMIT 5;
```

### Login Issues

If you can't log in:
1. Check username/password (case-sensitive)
2. Clear browser cookies
3. Restart the Flask app

### Scraping Fails

Common causes:
- Invalid Apify API token
- Target site is not Shopify
- Apify account out of credits
- Network connectivity issues

Check logs for detailed errors.

### Products Not Pushing to Shopify

Verify:
- Shopify API token is valid
- Token has `write_products` scope
- Shop URL is correct format
- Network connectivity

## File Structure

```
kasim/
├── app.py                          # Main Flask application
├── models.py                       # Database models
├── database.py                     # Database service layer
├── requirements.txt                # Python dependencies
├── .env                           # Environment variables
├── .env.example                   # Example configuration
├── shopify_automation.db          # SQLite database
│
├── services/
│   ├── apify_service.py          # Apify integration
│   ├── shopify_service.py        # Shopify API client
│   ├── openai_service.py         # OpenAI integration
│   ├── gemini_service.py         # Google Gemini
│   ├── product_mapper.py         # Data transformation
│   └── image_processor.py        # Image handling
│
└── templates/
    ├── base.html                 # Base template with navbar
    ├── login.html                # Login page
    ├── dashboard.html            # Dashboard
    ├── scrape.html               # Scraping page
    └── products.html             # Products management
```

## Security Notes

⚠️ **Important**:
- Change the `SECRET_KEY` in production
- Use HTTPS in production
- Consider implementing proper user management for multi-user scenarios
- Keep API tokens secure and never commit to git

## Limitations & Notes

- Single-user authentication system
- SQLite database (migrate to PostgreSQL for production)
- OpenAI enhancement is optional (can be slow and costly)
- Google Gemini image enhancement not fully implemented
- Images are stored by URL, not uploaded to your server

## Upgrading to PostgreSQL

For production, use PostgreSQL:

```bash
pip install psycopg2-binary
```

Update `.env`:
```env
DATABASE_URL=postgresql://username:password@host:5432/database
```

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review logs for error details
3. Verify all API credentials are correct
4. Ensure dependencies are installed

## Changelog

**v2.0** - Database-backed system with UI
- Added SQLite database
- Added login system
- Added product review workflow
- Added bulk actions
- Added status tracking
- Improved UI/UX

**v1.0** - Initial N8N conversion
- Direct push to Shopify
- No database
- No review system

## License

MIT License

---

**Made with ❤️ for Shopify automation**
