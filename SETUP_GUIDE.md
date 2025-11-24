# Quick Setup Guide

## 🚀 Get Started in 3 Minutes

### Step 1: Install Dependencies
```bash
cd /Users/apple/Desktop/kasim
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure API Keys
```bash
cp .env.example .env
nano .env  # or use any text editor
```

**Required credentials:**
- `APIFY_API_TOKEN` - Get from https://console.apify.com/account/integrations
- `SHOPIFY_SHOP_URL` - Your store URL (e.g., https://yourstore.myshopify.com)
- `SHOPIFY_ACCESS_TOKEN` - Generate from Shopify Admin → Apps → Develop apps
- `SECRET_KEY` - Change to a random secure string

**✨ Note:** No OpenAI or Gemini API keys needed - system uses Apify last run!

### Step 3: Run the Application
```bash
python app.py
```

Visit: **http://localhost:5000**

### Step 4: Login
- **Username**: `Mahad`
- **Password**: `Mahad`

---

## 📋 Two-Step Workflow

### ⚡ STEP 1: Fetch Products from Apify Last Run
1. Go to **Scrape** page
2. Enter source URL (for reference)
3. Click **"Fetch Products from Last Run"**
4. Products saved to database automatically

**💡 Note:** Uses Apify's last run - NO new scraping, saves credits!

### ⚡ STEP 2: Push to Shopify
1. Go to **Products** page
2. Review all fetched products
3. Select products with checkboxes
4. Click **"Push to Shopify"**
5. Products get **(AI-GENERATED)** suffix automatically

### 🎯 Track Status
- ✅ = Product added to Shopify
- ❌ = Not yet added

---

## 🔧 Troubleshooting

### Can't login?
- Username and password are case-sensitive
- Try clearing browser cookies

### Fetching fails?
- Check Apify API token is correct
- Ensure Apify has a recent successful run
- Check network connectivity
- View logs for detailed error messages

### Can't push to Shopify?
- Verify Shopify access token
- Check token has `write_products` scope
- Ensure shop URL is correct

---

## 📊 Database Location

SQLite database is stored at:
```
/Users/apple/Desktop/kasim/shopify_automation.db
```

To reset database:
```bash
rm shopify_automation.db
python app.py  # Recreates tables
```

---

## 🎯 Features Summary

✅ Login system (Mahad/Mahad)
✅ Fetch from Apify last run (NO new scraping!)
✅ Save products to database
✅ Review before pushing to Shopify
✅ Bulk actions (approve, reject, push, delete)
✅ Status tracking (✅ added / ❌ not added)
✅ Dashboard with statistics
✅ Price transformation (divide by 100, multiply by 2)
✅ Auto-adds "(AI-GENERATED)" suffix to product names
✅ Uses original images or placeholders
✅ NO OpenAI or Gemini (saves credits!)

---

## 📁 Important Files

- `app.py` - Main application
- `models.py` - Database schema
- `templates/` - UI pages
- `services/` - API integrations
- `.env` - Your configuration
- `shopify_automation.db` - Product database

---

## 🆘 Need Help?

Check:
1. README.md - Full documentation
2. Terminal output - Error messages
3. Browser console - JavaScript errors
4. Database - `sqlite3 shopify_automation.db`

---

**You're all set!** 🎉

Start by visiting http://localhost:5000 and logging in with Mahad/Mahad.
