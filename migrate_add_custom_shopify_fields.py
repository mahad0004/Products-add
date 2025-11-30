"""
Database Migration: Add custom Shopify credentials fields to ai_jobs table
"""

import sqlite3
import os

def migrate_database():
    """Add custom_shopify_url and custom_access_token columns to ai_jobs table"""

    db_path = 'instance/shopify_automation.db'

    if not os.path.exists(db_path):
        print(f"❌ Database not found at: {db_path}")
        return False

    print(f"🔧 Migrating database: {db_path}")
    print("=" * 70)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(ai_jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        fields_to_add = []

        if 'custom_shopify_url' not in columns:
            fields_to_add.append('custom_shopify_url')

        if 'custom_access_token' not in columns:
            fields_to_add.append('custom_access_token')

        if not fields_to_add:
            print("✅ All custom Shopify fields already exist - no migration needed")
            conn.close()
            return True

        print(f"📝 Adding {len(fields_to_add)} new column(s) to ai_jobs table:")

        # Add missing columns
        for field in fields_to_add:
            print(f"   Adding column: {field}")
            cursor.execute(f"ALTER TABLE ai_jobs ADD COLUMN {field} VARCHAR(255)")

        conn.commit()

        print("\n✅ Migration completed successfully!")
        print("\nNew columns added:")
        print("   - custom_shopify_url: Store URL for custom Shopify store")
        print("   - custom_access_token: Admin API access token for custom store")
        print("\n💡 Usage: Leave these NULL to use default .env credentials,")
        print("   or set them to use a different Shopify store per AI job")

        conn.close()
        return True

    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        conn.rollback()
        conn.close()
        return False


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("DATABASE MIGRATION: Add Custom Shopify Credentials Fields")
    print("=" * 70)
    print()

    success = migrate_database()

    if success:
        print("\n" + "=" * 70)
        print("✅ Migration completed - database is ready!")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("❌ Migration failed - please check errors above")
        print("=" * 70)
