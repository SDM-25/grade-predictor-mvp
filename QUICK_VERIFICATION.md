# Quick Verification Guide

## ✅ Fix Applied Successfully!

The database path is now **absolute** and users will persist.

---

## Verify It Works (3 Steps)

### Step 1: Check Database Path
```bash
python -c "from db import SQLITE_PATH; print(SQLITE_PATH)"
```

**Expected output:**
```
C:\My Business\locking in 2026\Early Grade Trajectory & Warning System\grade_predictor.db
```

✅ Path should be **absolute** (starts with `C:\`)

---

### Step 2: Run Persistence Test
```bash
python test_db_persistence.py
```

**Expected output:**
```
Path Type: Absolute
[OK] User already exists (ID: 2)
[OK] This proves persistence is working!
Total users in database: 2
```

✅ Run it multiple times - user count stays at 2

---

### Step 3: Test in Streamlit

1. **Start Streamlit:**
   ```bash
   streamlit run app.py
   ```

2. **Check Database Diagnostics:**
   - Open the sidebar
   - Click "🔍 Database Diagnostics" expander
   - Verify the path is absolute
   - Note the file size

3. **Create a Test Account:**
   - Go to "Sign Up" tab
   - Create account: `test@example.com` / password: `test123`
   - Login successfully

4. **Reload Browser:**
   - Press F5 to reload
   - Check "Database Diagnostics" - path should be the same
   - Try logging in again
   - ✅ Account should still work!

5. **Edit app.py:**
   - Open `app.py` in your editor
   - Add a comment anywhere (e.g., `# test change`)
   - Save the file (Streamlit auto-reloads)
   - Check "Database Diagnostics" - path should be the same
   - Login again
   - ✅ Account should still work!

6. **Restart Streamlit:**
   - Stop Streamlit (Ctrl+C)
   - Start it again: `streamlit run app.py`
   - Check "Database Diagnostics" - path should be the same
   - Login again
   - ✅ Account should still work!

---

## Current Status

**Database Location:**
```
C:\My Business\locking in 2026\Early Grade Trajectory & Warning System\grade_predictor.db
```

**Current Users in Database:** 2
- User 1: Existing user
- User 2: Test persistence user (test_persistence@example.com)

---

## What Was Fixed

| Before | After |
|--------|-------|
| ❌ Relative path: `"grade_predictor.db"` | ✅ Absolute path: `APP_DIR / "grade_predictor.db"` |
| ❌ Users disappear on reload | ✅ Users persist across reloads |
| ❌ Path changes with working dir | ✅ Path always the same |
| ❌ No way to verify path | ✅ UI shows path in sidebar |

---

## Files Changed

1. **db.py** - Database path now absolute
2. **app.py** - Added diagnostics UI in sidebar
3. **test_db_persistence.py** - New test script

**Total lines changed:** ~25 lines
**New dependencies:** None (uses Python stdlib only)
**Breaking changes:** None (backward compatible)

---

## Troubleshooting

### If accounts still disappear:

1. **Check the diagnostics panel:**
   - Open sidebar in Streamlit
   - Expand "🔍 Database Diagnostics"
   - Screenshot the path and share it

2. **Verify the file exists:**
   ```bash
   dir "C:\My Business\locking in 2026\Early Grade Trajectory & Warning System\grade_predictor.db"
   ```

3. **Check the file isn't being deleted:**
   - Note the file size in diagnostics
   - Reload the page
   - File size should stay the same or increase (never decrease to 0)

4. **Run the test script:**
   ```bash
   python test_db_persistence.py
   ```
   - Should show "User already exists"
   - User count should stay at 2

---

**Status: ✅ FIXED**

Accounts will now persist across:
- Editing code
- Reloading browser
- Restarting Streamlit
