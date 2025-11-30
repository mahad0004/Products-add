"""
Database Migration: Add option name columns to Product and AIProduct tables
Run this once to update the database schema
"""

import sqlite3
import os

def migrate_database(db_path):
    """Add option name columns to products and ai_products tables"""
    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if products table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        if not cursor.fetchone():
            print(f"⏭️  Skipping {db_path} - 'products' table does not exist")
            conn.close()
            return

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(products)")
        existing_columns = [col[1] for col in cursor.fetchall()]

        # Add columns to products table if they don't exist
        if 'option1_name' not in existing_columns:
            print("Adding option name columns to 'products' table...")
            cursor.execute("ALTER TABLE products ADD COLUMN option1_name VARCHAR(200)")
            cursor.execute("ALTER TABLE products ADD COLUMN option2_name VARCHAR(200)")
            cursor.execute("ALTER TABLE products ADD COLUMN option3_name VARCHAR(200)")
            print("✅ Added option name columns to 'products' table")
        else:
            print("⏭️  Option name columns already exist in 'products' table")

        # Check if ai_products table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_products'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(ai_products)")
            existing_ai_columns = [col[1] for col in cursor.fetchall()]

            # Add columns to ai_products table if they don't exist
            if 'option1_name' not in existing_ai_columns:
                print("Adding option name columns to 'ai_products' table...")
                cursor.execute("ALTER TABLE ai_products ADD COLUMN option1_name VARCHAR(200)")
                cursor.execute("ALTER TABLE ai_products ADD COLUMN option2_name VARCHAR(200)")
                cursor.execute("ALTER TABLE ai_products ADD COLUMN option3_name VARCHAR(200)")
                print("✅ Added option name columns to 'ai_products' table")
            else:
                print("⏭️  Option name columns already exist in 'ai_products' table")
        else:
            print("⏭️  'ai_products' table does not exist yet (will be created on first AI job)")

        conn.commit()
        print("✅ Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {str(e)}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    # Find all database files
    db_files = [
        'shopify_automation.db',
        'instance/shopify_automation.db',
        'instance/products.db'
    ]

    migrated = False
    for db_file in db_files:
        if os.path.exists(db_file):
            migrate_database(db_file)
            migrated = True

    if not migrated:
        print("⚠️  No database files found. Schema will be created on first run.")
