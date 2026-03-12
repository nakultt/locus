"""
Database Migration Script for Incident Analysis Tables
Run this to add incident analysis tables to the database.
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
        # Check if tables already exist
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('repositories', 'incident_analyses', 'analysis_repositories', 
                              'error_patterns', 'suspect_commits', 'timeline_events', 'shareable_reports')
        """))
        
        existing_tables = [row[0] for row in result]
        
        if existing_tables:
            print(f"[INFO] Found existing tables: {existing_tables}")
            print("[INFO] Tables will be created if they don't exist")
        
        # Create repositories table
        print("[INFO] Creating repositories table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS repositories (
                id SERIAL PRIMARY KEY,
                owner VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                default_branch VARCHAR(100) NOT NULL DEFAULT 'main',
                github_token_encrypted TEXT,
                last_synced TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] repositories table created")
        
        # Create incident_analyses table
        print("[INFO] Creating incident_analyses table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS incident_analyses (
                id SERIAL PRIMARY KEY,
                analysis_uuid VARCHAR(36) UNIQUE NOT NULL,
                log_content TEXT NOT NULL,
                log_format VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP WITH TIME ZONE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] incident_analyses table created")
        
        # Create analysis_repositories junction table
        print("[INFO] Creating analysis_repositories table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS analysis_repositories (
                id SERIAL PRIMARY KEY,
                analysis_id INTEGER NOT NULL REFERENCES incident_analyses(id) ON DELETE CASCADE,
                repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] analysis_repositories table created")
        
        # Create error_patterns table
        print("[INFO] Creating error_patterns table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS error_patterns (
                id SERIAL PRIMARY KEY,
                error_type VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                file_paths TEXT,
                function_names TEXT,
                line_numbers TEXT,
                timestamps TEXT,
                raw_stack_trace TEXT,
                analysis_id INTEGER NOT NULL REFERENCES incident_analyses(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] error_patterns table created")
        
        # Create suspect_commits table
        print("[INFO] Creating suspect_commits table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suspect_commits (
                id SERIAL PRIMARY KEY,
                commit_sha VARCHAR(40) NOT NULL,
                author_name VARCHAR(255),
                author_email VARCHAR(255),
                commit_message TEXT,
                commit_timestamp TIMESTAMP WITH TIME ZONE,
                confidence_score INTEGER NOT NULL DEFAULT 0,
                matching_files TEXT,
                matching_functions TEXT,
                pr_number INTEGER,
                pr_title VARCHAR(500),
                analysis_id INTEGER NOT NULL REFERENCES incident_analyses(id) ON DELETE CASCADE,
                repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] suspect_commits table created")
        
        # Create timeline_events table
        print("[INFO] Creating timeline_events table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS timeline_events (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                event_metadata TEXT,
                analysis_id INTEGER NOT NULL REFERENCES incident_analyses(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] timeline_events table created")
        
        # Create shareable_reports table
        print("[INFO] Creating shareable_reports table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS shareable_reports (
                id SERIAL PRIMARY KEY,
                share_uuid VARCHAR(36) UNIQUE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITH TIME ZONE,
                access_count INTEGER NOT NULL DEFAULT 0,
                analysis_id INTEGER NOT NULL REFERENCES incident_analyses(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("[OK] shareable_reports table created")
        
        # Create indexes for better query performance
        print("[INFO] Creating indexes...")
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_repositories_user_id ON repositories(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_incident_analyses_user_id ON incident_analyses(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_incident_analyses_uuid ON incident_analyses(analysis_uuid)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_analysis_repositories_analysis_id ON analysis_repositories(analysis_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_analysis_repositories_repository_id ON analysis_repositories(repository_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_error_patterns_analysis_id ON error_patterns(analysis_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_suspect_commits_analysis_id ON suspect_commits(analysis_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_suspect_commits_repository_id ON suspect_commits(repository_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_timeline_events_analysis_id ON timeline_events(analysis_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_shareable_reports_analysis_id ON shareable_reports(analysis_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_shareable_reports_uuid ON shareable_reports(share_uuid)"))
        conn.commit()
        print("[OK] Indexes created")
        
        # Show created tables
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('repositories', 'incident_analyses', 'analysis_repositories', 
                              'error_patterns', 'suspect_commits', 'timeline_events', 'shareable_reports')
            ORDER BY table_name
        """))
        
        print("\n[INFO] Incident analysis tables:")
        for row in result:
            print(f"   - {row[0]}")
            
    print("\n[DONE] Database migration complete!")
    
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
