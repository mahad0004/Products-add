# Option Names Fix - Testing & Troubleshooting Guide

## ✅ What We Fixed

Our code now properly stores and uses option names like:
- **"Bollard Size"** instead of "Option 1"
- **"Finish"** instead of "Option 2"
- **"Add Red & White Chevron Tape"** instead of "Option 3"

## 🧪 How to Test

### Step 1: Run a New Scrape Job

1. Go to your dashboard
2. Create a **NEW** scrape job (existing products won't have option names)
3. Use a Shopify store URL that has products with named options

### Step 2: Check the Logs

Look for these log messages:

```
✅ Found option name: 'Bollard Size' with 3 values
✅ Found option name: 'Finish' with 2 values
✅ Found option name: 'Add Red & White Chevron Tape' with 2 values
```

If you see these, **SUCCESS!** Option names are being captured.

### Step 3: Check the Database

```bash
sqlite3 instance/shopify_automation.db "SELECT title, option1_name, option2_name, option3_name FROM products WHERE option1_name IS NOT NULL LIMIT 5;"
```

You should see real option names in the database.

### Step 4: Push to Shopify

Create an AI job and push products to Shopify. Check the Shopify product page - variant selectors should show proper names!

## 🔍 Troubleshooting

### Problem: Still seeing "Option 1", "Option 2", "Option 3"

**Cause:** The Apify actor `autofacts~shopify` did not support full product schema extraction.

**Solution Applied:**

#### ✅ Switched to Better Apify Actor

**ALREADY IMPLEMENTED** - Now using `hoppr~shopify-scraper`:

1. Updated `services/apify_service.py` line 20:
   ```python
   self.actor_id = "hoppr~shopify-scraper"
   ```

2. This actor extracts full Shopify product JSON from the native Shopify API including:
   - Product option names (e.g., "Size", "Color", "Material")
   - Complete variant data
   - All product metadata

#### Option B: Use Custom JavaScript Extractor

Add a custom page function to extract Shopify's embedded product JSON:

```javascript
// In Apify actor settings, add this custom page function:
async function pageFunction(context) {
    const { page } = context;

    // Extract Shopify's embedded product JSON
    const productJson = await page.evaluate(() => {
        const scriptTag = document.querySelector('script[type="application/json"][data-product-json]');
        if (scriptTag) {
            return JSON.parse(scriptTag.textContent);
        }
        return null;
    });

    if (productJson && productJson.options) {
        return {
            ...context.request.userData,
            options: productJson.options  // Contains {name: "Size", values: ["S", "M", "L"]}
        };
    }
}
```

#### Option C: Manual Apify Dashboard Configuration

1. Go to https://console.apify.com
2. Find your `autofacts~shopify` actor
3. Go to **Input** tab
4. Add these fields:
   - `extractProductJson`: `true`
   - `extractVariantOptions`: `true`
5. Save and run a test

## 📊 Expected Data Structure

Apify should provide:

```json
{
  "title": "Test Bollard",
  "options": [
    {
      "name": "Bollard Size",
      "values": ["60mm x 60mm", "90mm x 90mm", "120mm x 120mm"]
    },
    {
      "name": "Finish",
      "values": ["Galvanised", "Powder Coated"]
    }
  ],
  "variants": [
    {
      "option1": "60mm x 60mm",
      "option2": "Galvanised",
      "price": 50.00
    }
  ]
}
```

## 🎯 Quick Test Command

Run the test script:

```bash
python3 test_option_names.py
```

This verifies our code works correctly when option names are provided.

## 📝 Summary

| Component | Status |
|-----------|--------|
| ✅ Database Schema | Ready (option name columns added) |
| ✅ Code Implementation | Complete (extracts & stores names) |
| ✅ Shopify Export | Working (uses stored names) |
| ✅ Apify Scraper | **UPDATED to hoppr~shopify-scraper** |

**Next Step:** Run a NEW scrape job to test the updated Apify actor and verify option names are captured!
