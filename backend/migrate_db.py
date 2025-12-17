"""
Database Migration Script
Run this ONCE to add the 'name' column to the users table.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("[ERROR] DATABASE_URL not found in .env file")
    exit(1)

# Fix for Render PostgreSQL URL (postgres:// -> postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print("[INFO] Connecting to database...")

try:
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Check if 'name' column exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'name'
        """))
        
        if result.fetchone():
            print("[OK] Column 'name' already exists in users table")
        else:
            # Add the name column
            conn.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR(255)"))
            conn.commit()
            print("[OK] Successfully added 'name' column to users table!")
        
        # Show current table structure
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """))
        
        print("\n[INFO] Current 'users' table structure:")
        for row in result:
            print(f"   - {row[0]}: {row[1]}")
            
        # Check integrations table
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'integrations'
        """))
        
        columns = [row[0] for row in result]
        if columns:
            print(f"\n[INFO] 'integrations' table exists with columns: {columns}")
        else:
            print("\n[WARN] 'integrations' table doesn't exist - it will be created on first use")
            
    print("\n[DONE] Database migration complete!")
    
except Exception as e:
    print(f"[ERROR] {e}")
