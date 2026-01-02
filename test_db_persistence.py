"""
Test script to verify database persistence.
Run this to confirm the database path is absolute and users persist.
"""

from pathlib import Path
from db import SQLITE_PATH, APP_DIR, init_db, create_user, get_user_by_email, get_total_users

print("="*60)
print("DATABASE PERSISTENCE TEST")
print("="*60)

# Show paths
print(f"\n1. Database Configuration:")
print(f"   App Directory: {APP_DIR}")
print(f"   Database Path: {SQLITE_PATH}")
print(f"   Path Type: {'Absolute' if Path(SQLITE_PATH).is_absolute() else 'Relative'}")

# Check if file exists
db_path = Path(SQLITE_PATH)
print(f"\n2. Database File Status:")
print(f"   Exists: {db_path.exists()}")
if db_path.exists():
    print(f"   Size: {db_path.stat().st_size:,} bytes")

# Initialize database
print(f"\n3. Initializing Database...")
init_db()
print(f"   [OK] Database initialized")

# Count existing users
total_users = get_total_users()
print(f"\n4. Current Users: {total_users}")

# Try to create a test user (or get if exists)
test_email = "test_persistence@example.com"
print(f"\n5. Testing User Creation:")
print(f"   Email: {test_email}")

existing_user = get_user_by_email(test_email)
if existing_user:
    print(f"   [OK] User already exists (ID: {existing_user['id']})")
    print(f"   [OK] This proves persistence is working!")
else:
    try:
        user_id = create_user(test_email, "testuser", "test123")
        print(f"   [OK] New user created (ID: {user_id})")
        print(f"   -> Reload this script to verify persistence")
    except Exception as e:
        print(f"   [ERROR] Error creating user: {e}")

# Final status
print(f"\n6. Final Verification:")
total_users_after = get_total_users()
print(f"   Total users in database: {total_users_after}")
print(f"   Database file: {SQLITE_PATH}")

print("\n" + "="*60)
print("TEST COMPLETE")
print("="*60)
print("\nNext steps:")
print("1. Run this script multiple times - user count should persist")
print("2. Start Streamlit and create an account")
print("3. Reload Streamlit - account should still exist")
print("4. Check 'Database Diagnostics' in sidebar to see the path")
print("="*60)
