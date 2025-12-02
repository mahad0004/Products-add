# Railway Volume Setup Guide - Database Persistence

This guide will help you set up a persistent volume in Railway so your SQLite database survives deployments.

## Problem
Without a volume, Railway rebuilds your container on every git push, **deleting your database** and all products.

## Solution
Mount a Railway Volume to persist the database across deployments.

---

## Step-by-Step Setup

### 1. Create a Volume in Railway Dashboard

1. Go to your Railway project: https://railway.app
2. Click on your service (the one running this app)
3. Go to the **"Settings"** tab
4. Scroll down to **"Volumes"** section
5. Click **"+ Add Volume"**
6. Configure the volume:
   ```
   Mount Path: /data
   ```
7. Click **"Add"** to create the volume

### 2. Set Environment Variable (Optional)

The app is already configured to use `/data` as the default path, but you can override it:

1. In Railway Dashboard → **"Variables"** tab
2. Add a new variable (optional):
   ```
   DATABASE_PATH=/data/shopify_automation.db
   ```
3. Click **"Add"** to save

### 3. Deploy the Changes

1. **Push the updated code** (already done with the database path update)
2. Railway will automatically redeploy with the volume mounted
3. Watch the deployment logs to confirm:
   ```
   📁 Using Railway volume database path: /data/shopify_automation.db
   ```

### 4. Verify Persistence

**Test that it works:**

1. Add some products to your database via the web UI
2. Make a small code change (add a comment somewhere)
3. Commit and push to trigger a redeploy:
   ```bash
   git add .
   git commit -m "Test: Verify database persistence"
   git push
   ```
4. After redeployment, check if your products are still there ✅

---

## How It Works

### Before (No Volume)
```
Git Push → Railway Rebuild → Fresh Container → Empty Database 💀
```

### After (With Volume)
```
Git Push → Railway Rebuild → Fresh Container → Volume Mounted → Database Persists ✅
```

The `/data` directory is now **persistent** and survives container rebuilds.

---

## Code Changes Made

The app now automatically detects the volume:

```python
# In app.py lines 77-98
DATABASE_PATH = os.getenv('DATABASE_PATH', '/data/shopify_automation.db')
if not os.path.exists(os.path.dirname(DATABASE_PATH)) and os.path.dirname(DATABASE_PATH) != '':
    # Local development fallback
    DATABASE_PATH = 'shopify_automation.db'
    logger.info(f"📁 Using local database path: {DATABASE_PATH}")
else:
    # Railway volume
    logger.info(f"📁 Using Railway volume database path: {DATABASE_PATH}")
```

**Local Development:** Uses `shopify_automation.db` in current directory
**Railway Production:** Uses `/data/shopify_automation.db` in persistent volume

---

## Troubleshooting

### Volume Not Working?

1. **Check the mount path**: Must be exactly `/data` (case-sensitive)
2. **Check logs**: Look for "Using Railway volume database path" message
3. **Redeploy**: Sometimes you need to trigger a fresh deploy after adding volume

### Database Still Empty After Volume Setup?

If you added the volume **after** deploying, your database might have been in the old location:

**Solution:** You'll need to re-scrape your products (the old database is gone)

### Want to Back Up Your Database?

Railway volumes can be accessed via Railway CLI:

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login
railway login

# Link to your project
railway link

# Download database
railway run cat /data/shopify_automation.db > backup.db
```

---

## Alternative: PostgreSQL

If you outgrow SQLite, upgrade to Railway's PostgreSQL add-on:

1. Railway Dashboard → **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Railway auto-adds `DATABASE_URL` variable
3. No code changes needed (app already supports PostgreSQL)

**When to upgrade:**
- High traffic / concurrent users
- Need better concurrency
- Database > 100MB

---

## Summary

✅ **Volume Mount Path:** `/data`
✅ **Database Location:** `/data/shopify_automation.db`
✅ **Persistence:** Database survives deployments
✅ **Auto-configured:** Works automatically after volume is added

Your database will now persist across all Railway deployments! 🎉
