"""
Database Migration: Fix custom Shopify credentials fields
- Remove incorrect columns (custom_api_key, custom_password)
- Add correct column (custom_access_token)
"""

import sqlite3
import os

def migrate_database():
    """Fix custom Shopify credentials fields in ai_jobs table"""

    db_path = 'instance/shopify_automation.db'

    if not os.path.exists(db_path):
        print(f"❌ Database not found at: {db_path}")
        return False

    print(f"🔧 Migrating database: {db_path}")
    print("=" * 70)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check current columns
        cursor.execute("PRAGMA table_info(ai_jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        print("Current custom Shopify columns:")
        for col in ['custom_shopify_url', 'custom_api_key', 'custom_password', 'custom_access_token']:
            if col in columns:
                print(f"   ✓ {col}")

        # SQLite doesn't support DROP COLUMN in older versions
        # We need to recreate the table

        print("\n📝 Recreating ai_jobs table with correct columns...")

        # Get all data from ai_jobs
        cursor.execute("SELECT * FROM ai_jobs")
        all_data = cursor.fetchall()

        # Get column names (excluding the ones we want to remove)
        cursor.execute("PRAGMA table_info(ai_jobs)")
        old_columns = cursor.fetchall()

        # Build new column list (exclude custom_api_key and custom_password)
        new_columns = []
        for col in old_columns:
            col_name = col[1]
            if col_name not in ['custom_api_key', 'custom_password']:
                new_columns.append(col)

        # Add custom_access_token if not present
        if 'custom_access_token' not in [c[1] for c in new_columns]:
            new_columns.append((len(new_columns), 'custom_access_token', 'VARCHAR(255)', 0, None, 0))

        # Create new table schema
        create_table_sql = """
        CREATE TABLE ai_jobs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_job_id INTEGER NOT NULL,
            source_job_task_id VARCHAR(255),
            status VARCHAR(50) DEFAULT 'pending',
            ai_products_created INTEGER DEFAULT 0,
            products_pushed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT,
            custom_shopify_url VARCHAR(255),
            custom_access_token VARCHAR(255),
            FOREIGN KEY (source_job_id) REFERENCES scrape_jobs (id) ON DELETE CASCADE
        )
        """

        cursor.execute(create_table_sql)

        # Copy data from old table to new table
        # Map old columns to new columns
        if all_data:
            # Get indices of columns we want to keep
            old_col_names = [col[1] for col in old_columns]

            # Build insert statement
            insert_cols = ['id', 'source_job_id', 'source_job_task_id', 'status',
                          'ai_products_created', 'products_pushed', 'created_at',
                          'completed_at', 'error_message', 'custom_shopify_url',
                          'custom_access_token']

            placeholders = ','.join(['?' for _ in insert_cols])
            insert_sql = f"INSERT INTO ai_jobs_new ({','.join(insert_cols)}) VALUES ({placeholders})"

            for row in all_data:
                # Map old row to new row
                new_row = []
                for col_name in insert_cols:
                    if col_name in old_col_names:
                        idx = old_col_names.index(col_name)
                        new_row.append(row[idx])
                    else:
                        # custom_access_token is new, set to NULL
                        new_row.append(None)

                cursor.execute(insert_sql, new_row)

        # Drop old table and rename new table
        cursor.execute("DROP TABLE ai_jobs")
        cursor.execute("ALTER TABLE ai_jobs_new RENAME TO ai_jobs")

        conn.commit()

        print("\n✅ Migration completed successfully!")
        print("\nFixed columns:")
        print("   ✓ Removed: custom_api_key")
        print("   ✓ Removed: custom_password")
        print("   ✓ Added: custom_access_token")
        print("\nFinal custom Shopify fields:")
        print("   - custom_shopify_url: Store URL for custom Shopify store")
        print("   - custom_access_token: Admin API access token for custom store")

        conn.close()
        return True

    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        return False


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("DATABASE MIGRATION: Fix Custom Shopify Credentials Fields")
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
