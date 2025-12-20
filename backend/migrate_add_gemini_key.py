"""
Migration script to add encrypted_gemini_key column to users table.
Run this once to sync your database with the updated User model.
"""

from sqlalchemy import text
from app.database import engine

def migrate():
    """Add encrypted_gemini_key column to users table if it doesn't exist."""
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'encrypted_gemini_key'
        """))
        
        if result.fetchone() is None:
            print("Adding 'encrypted_gemini_key' column to users table...")
            conn.execute(text("ALTER TABLE users ADD COLUMN encrypted_gemini_key TEXT"))
            conn.commit()
            print("[OK] Column added successfully!")
        else:
            print("[OK] Column 'encrypted_gemini_key' already exists. No changes needed.")

if __name__ == "__main__":
    migrate()
