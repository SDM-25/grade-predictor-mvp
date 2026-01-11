from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import re

# App version: 2026-01-06-v2 (gap_score fix)
# Import database module
from db import (
    init_db, get_or_create_user, get_or_create_course,
    read_sql, execute, execute_returning, fetchone, fetchall,
    is_postgres, get_conn,
    get_course_total_marks, get_next_due_date, ensure_default_assessment, get_assessments,
    # Auth functions
    hash_password, verify_password, create_user, get_user_by_email, update_last_login,
    # Auth tokens (persistent login)
    generate_token, hash_token, store_token, validate_token, revoke_token, cleanup_expired_tokens,
    # Session tracking
    upsert_session, end_session, get_live_users_count,
    # Legacy data functions
    has_legacy_data, get_legacy_data_counts, claim_legacy_data,
    # Admin functions
    verify_admin, get_admin_stats, log_event,
    # Database path (for diagnostics)
    SQLITE_PATH, APP_DIR
)
import uuid

# Import cookie manager for persistent login
try:
    import extra_streamlit_components as stx
    HAS_COOKIE_MANAGER = True
except ImportError:
    HAS_COOKIE_MANAGER = False

# Import PDF extractor (optional)
try:
    from pdf_extractor import extract_and_process_topics, normalize_text, HAS_PYMUPDF
except ImportError:
    HAS_PYMUPDF = False

# Import dashboard helpers
from dashboard_helpers import (
    get_all_courses, get_all_upcoming_assessments,
    get_course_topic_count, get_course_assessment_count,
    compute_course_snapshot, generate_recommended_tasks,
    get_at_risk_courses, get_next_prerequisite_step
)

# Import UI components
from ui import (
    inject_css, render_kpi_row, status_badge, render_empty_state,
    render_action_list, section_header, card_start, card_end
)

# Import metric computation functions (NO Streamlit UI dependencies)
from metrics import compute_mastery, decay_factor, compute_readiness


def generate_recommendations(topics_scored: pd.DataFrame, upcoming_lectures: pd.DataFrame, days_left: int, today: date, is_retake: bool = False) -> list:
    """Generate smart study recommendations based on gaps, lectures, and exam proximity."""
    recommendations = []
    
    if topics_scored.empty:
        return ["Add topics to get personalized recommendations."]
    
    gaps = topics_scored.sort_values("gap_score", ascending=False)
    
    if not is_retake and not upcoming_lectures.empty:
        for _, lec in upcoming_lectures.iterrows():
            lec_date = pd.to_datetime(lec["lecture_date"]).date()
            days_until = (lec_date - today).days
            if 0 <= days_until <= 3:
                topics_planned = lec["topics_planned"] or ""
                for topic in topics_planned.split(","):
                    topic = topic.strip()
                    if topic:
                        match = topics_scored[topics_scored["topic_name"].str.lower().str.contains(topic.lower(), na=False)]
                        if not match.empty:
                            mastery = match.iloc[0]["mastery"]
                            if mastery < 2:
                                recommendations.append(f"🔴 **URGENT**: Review **{topic}** before lecture on {lec_date.strftime('%a %d/%m')}")
                            elif mastery < 4:
                                recommendations.append(f"🟡 **Prep**: Brush up on **{topic}** before lecture on {lec_date.strftime('%a %d/%m')}")
    
    if days_left <= 7:
        priority = "🚨 EXAM WEEK"
        top_gaps = gaps.head(3)
        for _, g in top_gaps.iterrows():
            if g["readiness"] < 0.6:
                recommendations.append(f"{priority}: Focus on **{g['topic_name']}** (weight: {g['weight_points']}, readiness: {g['readiness']*100:.0f}%)")
    elif days_left <= 14:
        top_gaps = gaps.head(4)
        for _, g in top_gaps.iterrows():
            if g["readiness"] < 0.7:
                recommendations.append(f"⚠️ **2 weeks left**: Prioritize **{g['topic_name']}** (gap score: {g['gap_score']:.1f})")
    elif days_left <= 30:
        top_gaps = gaps.head(5)
        for _, g in top_gaps.iterrows():
            if g["mastery"] < 3:
                recommendations.append(f"📚 Study **{g['topic_name']}** - mastery only {g['mastery']:.1f}/5")
    
    stale_topics = topics_scored[
        (topics_scored["mastery"] >= 2) & 
        (topics_scored["readiness"] < topics_scored["mastery"] / 5.0 * 0.7)
    ].head(3)
    for _, t in stale_topics.iterrows():
        recommendations.append(f"🔄 **Refresh**: {t['topic_name']} - mastery decaying (last activity: {t['last_activity'] or 'never'})")
    
    untouched = topics_scored[topics_scored["mastery"] == 0].sort_values("weight_points", ascending=False).head(2)
    for _, t in untouched.iterrows():
        if t["weight_points"] > 0:
            recommendations.append(f"🆕 **Start**: {t['topic_name']} (worth {t['weight_points']} points, not yet studied)")
    
    if not recommendations:
        avg_readiness = topics_scored["readiness"].mean()
        if avg_readiness >= 0.8:
            recommendations.append("✅ **Great progress!** Focus on practice exams and timed exercises.")
        elif avg_readiness >= 0.6:
            recommendations.append("📈 **Good progress!** Keep up the consistent study sessions.")
        else:
            recommendations.append("📚 **More work needed.** Prioritize high-weight topics first.")
    
    return recommendations[:8]

# ============ STREAMLIT APP ============

# Developer mode flag - set to True to show internal diagnostics in sidebar
DEV_MODE = False

st.set_page_config(page_title="Exam Readiness Predictor", page_icon="📈", layout="wide")
init_db()

# Inject global CSS styling
inject_css()

# Show database mode indicator (internal use)
db_mode = "🐘 Postgres (Supabase)" if is_postgres() else "📁 SQLite (Local)"

# ============ DATABASE DIAGNOSTICS (DEV ONLY) ============
# Display database path and status for debugging persistence issues
if DEV_MODE and not is_postgres():
    from pathlib import Path
    db_path = Path(SQLITE_PATH)
    db_exists = db_path.exists()

    with st.sidebar:
        with st.expander("🔍 Database Diagnostics", expanded=False):
            st.caption("**Database Path:**")
            st.code(str(SQLITE_PATH), language=None)
            st.caption(f"**File Exists:** {'✅ Yes' if db_exists else '❌ No'}")
            if db_exists:
                db_size = db_path.stat().st_size
                st.caption(f"**File Size:** {db_size:,} bytes")
            st.caption(f"**App Directory:** {str(APP_DIR)}")

# ============ SESSION STATE INITIALIZATION ============
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.user_email = None
    st.session_state.is_admin = False

# Session ID for tracking (generated once per browser session)
# SECURITY: Use cryptographically secure token instead of UUID
if "session_id" not in st.session_state:
    from security import generate_secure_token
    st.session_state.session_id = generate_secure_token(24)

# Wizard state
if "wizard_step" not in st.session_state:
    st.session_state.wizard_step = 0
if "wizard_data" not in st.session_state:
    st.session_state.wizard_data = {}

# Study plan defaults
if "hours_per_week" not in st.session_state:
    st.session_state.hours_per_week = 10
if "session_length" not in st.session_state:
    st.session_state.session_length = 60

# Empty state navigation flag
if "navigate_to_exams" not in st.session_state:
    st.session_state.navigate_to_exams = False

# ============ AUTO-LOGIN WITH PERSISTENT TOKEN ============
# Initialize cookie manager
if HAS_COOKIE_MANAGER:
    cookie_manager = stx.CookieManager()

    # Try auto-login only if not already logged in
    if st.session_state.user_id is None:
        # Get auth token from cookie
        auth_token = cookie_manager.get("auth_token")

        if auth_token:
            # Validate token
            token_data = validate_token(auth_token)

            if token_data:
                # Token is valid - auto-login
                st.session_state.user_id = token_data["user_id"]
                st.session_state.user_email = token_data["email"]
                st.session_state.is_admin = False  # Regular user login
                update_last_login(token_data["user_id"])
                # Rerun to show authenticated page
                st.rerun()
            else:
                # Token is invalid/expired - delete cookie
                cookie_manager.delete("auth_token")

# ============ AUTHENTICATION GATE ============
def show_auth_page():
    """Show login/signup page. Returns True if user is authenticated."""
    st.title("Exam Readiness Predictor")
    st.caption("Track your study progress and predict your exam grades.")

    login_tab, signup_tab, admin_tab = st.tabs(["Login", "Sign Up", "Admin"])
    
    # Login tab
    with login_tab:
        st.subheader("Login to Your Account")
        with st.form("login_form"):
            login_email = st.text_input("Email", placeholder="you@example.com", key="login_email_input")
            login_password = st.text_input("Password", type="password", key="login_password_input")
            remember_me = st.checkbox(
                "Remember me (stay logged in for 30 days)",
                value=True,
                help="Keep you logged in even after closing the browser. Uncheck for session-only login."
            )

            submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

            if submitted:
                if not login_email or not login_password:
                    st.error("Please enter email and password.")
                else:
                    # SECURITY: Rate limit login attempts (5 attempts per minute per email)
                    from security import check_rate_limit, get_rate_limit_retry_after, sanitize_string
                    rate_key = f"login:{sanitize_string(login_email.lower(), max_length=255)}"
                    if not check_rate_limit(rate_key, max_requests=5, window_seconds=60):
                        retry_after = get_rate_limit_retry_after(rate_key, window_seconds=60)
                        st.error(f"Too many login attempts. Please wait {retry_after} seconds.")
                    else:
                        user = get_user_by_email(login_email)
                        if user is None:
                            st.error("Email not found. Please sign up first.")
                        elif not user["password_hash"]:
                            st.error("This account has no password set. Please contact support.")
                        elif not verify_password(login_password, user["password_hash"]):
                            st.error("Incorrect password.")
                        else:
                            # Successful login
                            st.session_state.user_id = user["id"]
                            st.session_state.user_email = user["email"]
                            update_last_login(user["id"])
                            st.session_state.wizard_step = 0
                            st.session_state.wizard_data = {}

                            # Handle "Remember me" - create persistent token
                            if remember_me and HAS_COOKIE_MANAGER:
                                # Generate token valid for 30 days
                                raw_token = generate_token()
                                expires_at = datetime.now() + timedelta(days=30)

                                # Store hashed token in database
                                store_token(user["id"], raw_token, expires_at)

                                # Store raw token in cookie
                                cookie_manager.set(
                                    "auth_token",
                                    raw_token,
                                    expires_at=expires_at,
                                    key="auth_token_cookie"
                                )

                            st.success("Login successful!")
                            st.rerun()

        # Safe debug info
        if HAS_COOKIE_MANAGER:
            with st.expander("🔧 Debug: Auth Status", expanded=False):
                # Check session state
                has_session_user_id = st.session_state.user_id is not None
                st.write(f"**Session state has user_id:** `{has_session_user_id}`")

                # Check cookie
                auth_token = cookie_manager.get("auth_token")
                has_cookie = auth_token is not None
                st.write(f"**Auth cookie exists:** `{has_cookie}`")

                # Check DB token validity (only if cookie exists)
                has_valid_db_token = False
                if has_cookie and auth_token:
                    token_data = validate_token(auth_token)
                    has_valid_db_token = token_data is not None
                st.write(f"**Valid token in DB:** `{has_valid_db_token}`")

                # Summary
                st.divider()
                if has_session_user_id:
                    st.caption("✓ User is logged in (session active)")
                elif has_valid_db_token:
                    st.caption("⚠️ Valid token exists but session not set (should auto-login)")
                elif has_cookie:
                    st.caption("⚠️ Cookie exists but token is invalid/expired")
                else:
                    st.caption("ℹ️ Not logged in (manual login required)")
    
    # Signup tab
    with signup_tab:
        st.subheader("Create New Account")
        with st.form("signup_form"):
            signup_email = st.text_input("Email *", placeholder="you@example.com", key="signup_email_input")
            signup_username = st.text_input("Username (optional)", placeholder="johndoe", key="signup_username_input")
            signup_password = st.text_input("Password *", type="password", help="Minimum 8 characters", key="signup_password_input")
            signup_password_confirm = st.text_input("Confirm Password *", type="password", key="signup_password_confirm_input")
            
            submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

            if submitted:
                # SECURITY: Rate limit signup attempts (3 signups per 5 minutes per session)
                from security import check_rate_limit, get_rate_limit_retry_after
                rate_key = f"signup:{st.session_state.get('session_id', 'anonymous')}"
                if not check_rate_limit(rate_key, max_requests=3, window_seconds=300):
                    retry_after = get_rate_limit_retry_after(rate_key, window_seconds=300)
                    st.error(f"Too many signup attempts. Please wait {retry_after} seconds.")
                else:
                    errors = []

                    # Email validation
                    if not signup_email:
                        errors.append("Email is required.")
                    elif not re.match(r"[^@]+@[^@]+\.[^@]+", signup_email):
                        errors.append("Invalid email format.")

                    # Password validation
                    if not signup_password:
                        errors.append("Password is required.")
                    elif len(signup_password) < 8:
                        errors.append("Password must be at least 8 characters.")

                    if signup_password != signup_password_confirm:
                        errors.append("Passwords do not match.")

                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        try:
                            user_id = create_user(
                                signup_email,
                                signup_username if signup_username else None,
                                signup_password
                            )
                            st.session_state.user_id = user_id
                            st.session_state.user_email = signup_email.lower().strip()
                            update_last_login(user_id)
                            st.session_state.wizard_step = 0
                            st.success("Account created! Welcome!")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
    
    # Admin tab
    with admin_tab:
        st.subheader("Admin Login")
        st.caption("For system administrators only.")

        # Debug info: show which secrets are configured (without revealing values)
        with st.expander("🔧 Debug: Secrets Configuration", expanded=False):
            try:
                # Show all secret keys (safe - no values)
                secret_keys = list(st.secrets.keys())
                st.write("**Available secret keys:**")
                st.code(secret_keys)

                # Show specific admin secret presence
                has_username = "ADMIN_USERNAME" in st.secrets
                has_password_hash = "ADMIN_PASSWORD_HASH" in st.secrets
                has_password_plain = "ADMIN_PASSWORD" in st.secrets

                st.write("**Admin secret status:**")
                st.write(f"- ADMIN_USERNAME: `{has_username}`")
                st.write(f"- ADMIN_PASSWORD_HASH: `{has_password_hash}`")
                st.write(f"- ADMIN_PASSWORD: `{has_password_plain}`")
            except Exception as e:
                st.error(f"⚠️ Unable to read secrets: {e}")

        with st.form("admin_form"):
            admin_username = st.text_input("Admin Username", key="admin_username_input")
            admin_password = st.text_input("Admin Password", type="password", key="admin_password_input")

            submitted = st.form_submit_button("Admin Login", type="primary", use_container_width=True)

            if submitted:
                if not admin_username or not admin_password:
                    st.error("Please enter admin credentials.")
                else:
                    # SECURITY: Strict rate limit for admin login (3 attempts per 5 minutes)
                    from security import check_rate_limit, get_rate_limit_retry_after
                    rate_key = f"admin_login:{st.session_state.get('session_id', 'anonymous')}"
                    if not check_rate_limit(rate_key, max_requests=3, window_seconds=300):
                        retry_after = get_rate_limit_retry_after(rate_key, window_seconds=300)
                        st.error(f"Too many admin login attempts. Please wait {retry_after} seconds.")
                    else:
                        # Check if secrets are configured before attempting login
                        try:
                            has_username = "ADMIN_USERNAME" in st.secrets
                            has_password_hash = "ADMIN_PASSWORD_HASH" in st.secrets
                            has_password_plain = "ADMIN_PASSWORD" in st.secrets

                            if not has_username or (not has_password_hash and not has_password_plain):
                                st.error("Admin secrets not configured. Please set ADMIN_USERNAME and either ADMIN_PASSWORD_HASH or ADMIN_PASSWORD in Streamlit Cloud secrets.")
                            elif verify_admin(admin_username, admin_password):
                                st.session_state.user_id = -1  # Special admin ID
                                st.session_state.user_email = admin_username
                                st.session_state.is_admin = True
                                log_event(None, "admin_login", f'{{"username": "{admin_username}"}}')
                                st.success("Admin login successful!")
                                st.rerun()
                            else:
                                st.error("Invalid admin credentials.")
                        except Exception as e:
                            st.error(f"Error during admin login: {str(e)}")
    
    st.divider()
    if DEV_MODE:
        st.caption(f"Database: {db_mode}")

# Check if user is logged in - show auth page if not
if st.session_state.user_id is None:
    show_auth_page()
    st.stop()

# ============ ADMIN DASHBOARD ============
if st.session_state.is_admin:
    st.title("👑 Admin Dashboard")
    st.caption("System usage metrics and analytics.")
    
    # Logout button
    if st.button("🚪 Logout"):
        # Revoke token and clear cookie (for regular users, admin doesn't use persistent tokens)
        if HAS_COOKIE_MANAGER:
            auth_token = cookie_manager.get("auth_token")
            if auth_token:
                revoke_token(auth_token)
                cookie_manager.delete("auth_token")

        st.session_state.user_id = None
        st.session_state.user_email = None
        st.session_state.is_admin = False
        from security import generate_secure_token
        st.session_state.session_id = generate_secure_token(24)
        log_event(None, "admin_logout")
        st.rerun()
    
    st.divider()
    
    # Get admin stats
    stats = get_admin_stats()
    
    # Live users section
    st.subheader("🟢 Live Users")
    st.metric("Active Now (last 10 min)", stats["live_users"])
    
    st.divider()
    
    # User signups section
    st.subheader("👥 User Signups")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Users", stats["total_users"])
    col2.metric("Last Day", stats["users_day"])
    col3.metric("Last Week", stats["users_week"])
    col4.metric("Last Month", stats["users_month"])
    
    st.divider()
    
    # Course creation section
    st.subheader("📚 Course Creation Activity")
    st.caption("Unique users who created a course:")
    col1, col2, col3 = st.columns(3)
    col1.metric("Last Day", stats["course_creators_day"])
    col2.metric("Last Week", stats["course_creators_week"])
    col3.metric("Last Month", stats["course_creators_month"])
    
    st.metric("Total Courses Created (all time)", stats["total_courses_created"])

    st.divider()
    if DEV_MODE:
        st.caption(f"Database: {db_mode}")
    st.stop()

# ============ LEGACY DATA CLAIM ============
# Check for legacy data (rows with NULL user_id) on first login
if "legacy_checked" not in st.session_state:
    st.session_state.legacy_checked = False

if not st.session_state.legacy_checked and has_legacy_data():
    st.warning("📦 **Legacy Data Found**")
    st.info("We found data from before user accounts were introduced. Click below to claim this data to your account.")
    
    counts = get_legacy_data_counts()
    count_str = ", ".join([f"{v} {k}" for k, v in counts.items() if v > 0])
    st.caption(f"Found: {count_str}")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Claim Legacy Data", type="primary"):
            claimed = claim_legacy_data(st.session_state.user_id)
            st.session_state.legacy_checked = True
            st.success(f"Data claimed! You now own this data.")
            st.rerun()
    with col2:
        if st.button("⏭️ Skip"):
            st.session_state.legacy_checked = True
            st.rerun()
    st.stop()
else:
    st.session_state.legacy_checked = True

# ============ SESSION TRACKING ============
# Update session on every page load for logged-in users
if st.session_state.user_id is not None:
    upsert_session(st.session_state.user_id, st.session_state.session_id)

# ============ ONBOARDING WIZARD ============
def show_onboarding_wizard(user_id: int):
    """Show 3-step onboarding wizard for first-time users."""
    
    st.title("🎓 Welcome to Exam Readiness Predictor!")
    st.caption("Let's set up your first course in under 2 minutes.")
    
    # Progress indicator
    steps = ["📚 Course", "📅 Exam", "📖 Topics"]
    cols = st.columns(3)
    for i, (col, step) in enumerate(zip(cols, steps)):
        if i < st.session_state.wizard_step:
            col.success(f"✅ {step}")
        elif i == st.session_state.wizard_step:
            col.info(f"👉 {step}")
        else:
            col.write(f"⏳ {step}")
    
    st.divider()
    
    # Step 1: Create Course
    if st.session_state.wizard_step == 0:
        st.header("Step 1: Create Your Course")
        st.write("What course are you preparing for?")
        
        with st.form("wizard_course"):
            course_name = st.text_input("Course name *", placeholder="e.g., Microeconomics, Data Structures, Organic Chemistry")
            
            col1, col2 = st.columns(2)
            with col1:
                total_marks = st.number_input("Total exam marks", min_value=1, value=120, help="Maximum marks for the exam")
            with col2:
                target_marks = st.number_input("Your target marks", min_value=0, value=90, help="What score are you aiming for?")
            
            submitted = st.form_submit_button("Next →", type="primary", use_container_width=True)
            
            if submitted:
                if course_name.strip():
                    # Create the course
                    course_id = get_or_create_course(user_id, course_name.strip())
                    execute("UPDATE courses SET total_marks=?, target_marks=? WHERE id=?", 
                           (total_marks, target_marks, course_id))
                    
                    st.session_state.wizard_data["course_id"] = course_id
                    st.session_state.wizard_data["course_name"] = course_name.strip()
                    st.session_state.wizard_data["total_marks"] = total_marks
                    st.session_state.wizard_step = 1
                    st.rerun()
                else:
                    st.error("Please enter a course name.")
    
    # Step 2: Add Exam
    elif st.session_state.wizard_step == 1:
        st.header("Step 2: Add Your Exam")
        st.write(f"When is the exam for **{st.session_state.wizard_data['course_name']}**?")
        
        with st.form("wizard_exam"):
            exam_name = st.text_input("Exam name *", value="Final Exam", placeholder="e.g., Midterm, Final Exam")
            exam_date = st.date_input("Exam date *", value=date.today() + timedelta(days=60))
            is_retake = st.checkbox("🔄 This is a retake (no lectures)", value=False,
                                   help="Check if you're retaking the exam and won't attend lectures")
            
            col1, col2 = st.columns(2)
            with col1:
                back = st.form_submit_button("← Back", use_container_width=True)
            with col2:
                submitted = st.form_submit_button("Next →", type="primary", use_container_width=True)
            
            if back:
                st.session_state.wizard_step = 0
                st.rerun()
            
            if submitted:
                if exam_name.strip():
                    course_id = st.session_state.wizard_data["course_id"]
                    execute_returning(
                        "INSERT INTO exams(user_id, course_id, exam_name, exam_date, is_retake) VALUES(?,?,?,?,?)",
                        (user_id, course_id, exam_name.strip(), str(exam_date), 1 if is_retake else 0)
                    )
                    
                    st.session_state.wizard_data["exam_name"] = exam_name.strip()
                    st.session_state.wizard_data["exam_date"] = exam_date
                    st.session_state.wizard_step = 2
                    st.rerun()
                else:
                    st.error("Please enter an exam name.")
    
    # Step 3: Add Topics
    elif st.session_state.wizard_step == 2:
        st.header("Step 3: Add Your Topics")
        st.write("What topics will be covered in the exam? Add one per line.")
        st.caption("💡 Tip: You can include weights like `Topic Name, 20` or just `Topic Name` (default weight: 10)")
        
        # Example topics
        example_topics = """Supply and Demand, 15
Market Equilibrium, 20
Elasticity, 15
Consumer Theory, 25
Producer Theory, 25"""
        
        with st.form("wizard_topics"):
            topics_text = st.text_area(
                "Topics (one per line) *",
                value="",
                placeholder=example_topics,
                height=200,
                help="Format: 'Topic Name' or 'Topic Name, weight'"
            )
            
            st.caption("Example format:")
            st.code(example_topics, language=None)
            
            col1, col2 = st.columns(2)
            with col1:
                back = st.form_submit_button("← Back", use_container_width=True)
            with col2:
                submitted = st.form_submit_button("🎉 Complete Setup", type="primary", use_container_width=True)
            
            if back:
                st.session_state.wizard_step = 1
                st.rerun()
            
            if submitted:
                if topics_text.strip():
                    course_id = st.session_state.wizard_data["course_id"]
                    lines = topics_text.strip().split("\n")
                    topics_added = 0
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Parse "Topic Name, weight" or just "Topic Name"
                        if "," in line:
                            parts = line.rsplit(",", 1)
                            topic_name = parts[0].strip()
                            try:
                                weight = float(parts[1].strip())
                            except ValueError:
                                weight = 10
                        else:
                            topic_name = line
                            weight = 10
                        
                        if topic_name:
                            execute_returning(
                                "INSERT INTO topics(user_id, course_id, topic_name, weight_points) VALUES(?,?,?,?)",
                                (user_id, course_id, topic_name, weight)
                            )
                            topics_added += 1
                    
                    if topics_added > 0:
                        # Complete wizard - set the newly created course as selected
                        course_name = st.session_state.wizard_data.get("course_name", "")
                        st.session_state.selected_course_name = course_name
                        st.session_state.wizard_step = -1  # Mark as completed
                        st.session_state.wizard_data = {}
                        st.balloons()
                        st.success(f"🎉 Setup complete! Added {topics_added} topics.")
                        st.rerun()
                    else:
                        st.error("Please add at least one topic.")
                else:
                    st.error("Please add at least one topic.")
    
    st.stop()

# ============ SIDEBAR ============
with st.sidebar:
    # User info and logout
    st.header("👤 Account")
    st.success(f"**{st.session_state.user_email}**")
    if st.button("🚪 Logout"):
        # Revoke persistent login token and clear cookie
        if HAS_COOKIE_MANAGER:
            auth_token = cookie_manager.get("auth_token")
            if auth_token:
                revoke_token(auth_token)
                cookie_manager.delete("auth_token")

        # End session tracking
        if st.session_state.user_id and st.session_state.session_id:
            end_session(st.session_state.user_id, st.session_state.session_id)
        st.session_state.user_id = None
        st.session_state.user_email = None
        st.session_state.wizard_step = 0
        st.session_state.wizard_data = {}
        st.session_state.legacy_checked = False
        # Generate new secure session_id for next login
        from security import generate_secure_token
        st.session_state.session_id = generate_secure_token(24)
        st.rerun()
    if DEV_MODE:
        st.caption(f"Database: {db_mode}")
    st.divider()
    
    # Get current user_id
    user_id = st.session_state.user_id
    
    # Check if user needs onboarding (no courses yet)
    courses = read_sql("SELECT * FROM courses WHERE user_id=?", (user_id,))
    
    if courses.empty and st.session_state.wizard_step >= 0:
        # Show wizard in main area (not sidebar)
        pass  # Will be handled after sidebar
    
    # Course setup (only show if user has courses)
    if not courses.empty:
        st.header("📚 Course Setup")
        
        course_options = courses["course_name"].tolist()
        
        new_course = st.text_input("Add new course", placeholder="e.g., Microeconomics")
        if st.button("Add Course") and new_course.strip():
            get_or_create_course(user_id, new_course.strip())
            st.rerun()

    course_options = courses["course_name"].tolist() if not courses.empty else []
    
    if course_options:
        # Initialize session state for selected course if needed
        if "selected_course_name" not in st.session_state or st.session_state.selected_course_name not in course_options:
            st.session_state.selected_course_name = course_options[0]
        
        selected_course = st.selectbox(
            "Select course", 
            course_options,
            index=course_options.index(st.session_state.selected_course_name),
            key="course_selector"
        )
        st.session_state.selected_course_name = selected_course
        
        course_id = int(courses.loc[courses["course_name"] == selected_course, "id"].iloc[0])
        course_row = courses[courses["course_name"] == selected_course].iloc[0]
        
        # Ensure at least one assessment exists (backward compatibility)
        ensure_default_assessment(user_id, course_id)
        
        # Get computed total marks from assessments
        course_total_marks = get_course_total_marks(user_id, course_id)
        if course_total_marks == 0:
            st.warning("⚠️ No assessments found. Go to Assessments tab to add one.")
            if st.button("📝 Create Default Assessment (120 marks)"):
                execute_returning(
                    """INSERT INTO assessments(user_id, course_id, assessment_name, assessment_type, marks, is_timed)
                       VALUES(?,?,?,?,?,?)""",
                    (user_id, course_id, "Final Exam", "Exam", 120, 1)
                )
                st.rerun()
            course_total_marks = 120  # Fallback for display
        
        st.metric("📊 Total Marks", f"{course_total_marks}", help="Sum of all assessment marks")

        # Advanced settings (collapsed by default)
        with st.expander("Advanced", expanded=False):
            # Target settings with toggle
            target_mode = st.radio("Target mode", ["Marks", "Percentage"], horizontal=True, key="target_mode")
            stored_target = int(course_row["target_marks"]) if course_row["target_marks"] else 90

            if target_mode == "Marks":
                target_marks = st.number_input("Target marks", min_value=0, max_value=course_total_marks, value=min(stored_target, course_total_marks))
                target_pct = (target_marks / course_total_marks * 100) if course_total_marks > 0 else 0
                st.caption(f"≈ {target_pct:.0f}%")
            else:
                target_pct = st.slider("Target %", min_value=0, max_value=100, value=int(stored_target / course_total_marks * 100) if course_total_marks > 0 else 75)
                target_marks = int(course_total_marks * target_pct / 100)
                st.caption(f"= {target_marks} marks")

            if st.button("💾 Save Target"):
                execute("UPDATE courses SET target_marks=? WHERE id=? AND user_id=?",
                       (target_marks, course_id, user_id))
                st.success("Target saved!")

            # Study plan settings
            st.divider()
            st.subheader("Study Plan Settings")
            hours_per_week = st.slider("Hours per week", min_value=1, max_value=40, value=10,
                                       help="How many hours can you dedicate to studying this course per week?")
            session_length = st.selectbox("Preferred session length",
                                          options=[30, 45, 60, 90, 120],
                                          index=2,
                                          format_func=lambda x: f"{x} mins",
                                          help="Your ideal study session duration")

            # Store in session state for dashboard access
            st.session_state.hours_per_week = hours_per_week
            st.session_state.session_length = session_length

        # Delete course section
        st.divider()
        with st.expander("🗑️ Delete Course", expanded=False):
            st.warning(f"⚠️ This will permanently delete **{selected_course}** and all its data.")
            confirm_delete = st.text_input("Type the course name to confirm deletion:", key="confirm_delete_course")
            if st.button("🗑️ Delete Course Permanently", type="primary"):
                if confirm_delete == selected_course:
                    # Get all topic IDs for this course to delete related data
                    topic_ids = fetchall("SELECT id FROM topics WHERE user_id=? AND course_id=?", (user_id, course_id))
                    with get_conn() as conn:
                        cur = conn.cursor()
                        for (tid,) in topic_ids:
                            if is_postgres():
                                cur.execute("DELETE FROM study_sessions WHERE topic_id=%s", (tid,))
                                cur.execute("DELETE FROM exercises WHERE topic_id=%s", (tid,))
                            else:
                                cur.execute("DELETE FROM study_sessions WHERE topic_id=?", (tid,))
                                cur.execute("DELETE FROM exercises WHERE topic_id=?", (tid,))
                        if is_postgres():
                            cur.execute("DELETE FROM topics WHERE user_id=%s AND course_id=%s", (user_id, course_id))
                            cur.execute("DELETE FROM scheduled_lectures WHERE user_id=%s AND course_id=%s", (user_id, course_id))
                            cur.execute("DELETE FROM exams WHERE user_id=%s AND course_id=%s", (user_id, course_id))
                            cur.execute("DELETE FROM courses WHERE id=%s AND user_id=%s", (course_id, user_id))
                        else:
                            cur.execute("DELETE FROM topics WHERE user_id=? AND course_id=?", (user_id, course_id))
                            cur.execute("DELETE FROM scheduled_lectures WHERE user_id=? AND course_id=?", (user_id, course_id))
                            cur.execute("DELETE FROM exams WHERE user_id=? AND course_id=?", (user_id, course_id))
                            cur.execute("DELETE FROM courses WHERE id=? AND user_id=?", (course_id, user_id))
                        conn.commit()
                    st.success("Course deleted!")
                    st.rerun()
                else:
                    st.error("Course name doesn't match. Deletion cancelled.")
    else:
        # No courses - wizard will handle this
        pass

# ============ CHECK FOR ONBOARDING ============
# Re-check courses after sidebar (in case we need wizard)
user_id = st.session_state.user_id
courses = read_sql("SELECT * FROM courses WHERE user_id=?", (user_id,))

if courses.empty and st.session_state.wizard_step >= 0:
    # First-time user - show onboarding wizard
    show_onboarding_wizard(user_id)

# If still no courses after wizard check, stop
if courses.empty:
    st.warning("Please complete the setup wizard to continue.")
    st.stop()

# At this point, we have courses - get the selected course from session state
# (These variables were already set in sidebar, but we need them in main scope)
course_options = courses["course_name"].tolist()
selected_course = st.session_state.get("selected_course_name", course_options[0])
if selected_course not in course_options:
    selected_course = course_options[0]
    st.session_state.selected_course_name = selected_course

course_id = int(courses.loc[courses["course_name"] == selected_course, "id"].iloc[0])
course_row = courses[courses["course_name"] == selected_course].iloc[0]

# Get computed total marks from assessments (not from course table)
ensure_default_assessment(user_id, course_id)
total_marks = get_course_total_marks(user_id, course_id)
if total_marks == 0:
    total_marks = 120  # Fallback
target_marks = int(course_row["target_marks"]) if course_row["target_marks"] else int(total_marks * 0.75)

st.title("Exam Readiness Predictor")
st.caption("Auto-calculated mastery from study sessions, exercises, and lectures.")

# ============ DIALOG FUNCTIONS ============
@st.dialog("Add Exam")
def add_exam_dialog():
    """Dialog for adding a new exam."""
    exam_name = st.text_input("Exam name", placeholder="e.g., Midterm, Final Exam")
    col1, col2 = st.columns(2)
    with col1:
        exam_date_input = st.date_input("Exam date", value=date.today() + timedelta(days=60))
    with col2:
        exam_marks = st.number_input("Marks", min_value=1, value=100, help="How many marks is this exam worth?")
    is_retake_input = st.checkbox("This is a retake (no lectures)", value=False,
                                  help="Retake exams exclude lectures from readiness calculations")

    col_cancel, col_submit = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with col_submit:
        if st.button("Add Exam", type="primary", use_container_width=True):
            if exam_name.strip():
                execute_returning("INSERT INTO exams(user_id, course_id, exam_name, exam_date, marks, is_retake) VALUES(?,?,?,?,?,?)",
                                 (user_id, course_id, exam_name.strip(), str(exam_date_input), exam_marks, 1 if is_retake_input else 0))
                st.session_state.exam_created_msg = f"Exam '{exam_name}' created!"
                st.rerun()
            else:
                st.error("Please enter an exam name.")

@st.dialog("Add Assessment")
def add_assessment_dialog():
    """Dialog for adding a new assessment."""
    asmt_name = st.text_input("Assessment name *", placeholder="e.g., Midterm Exam")
    asmt_type = st.selectbox("Type", ["Exam", "Assignment", "Project", "Quiz", "Other"])
    col1, col2 = st.columns(2)
    with col1:
        asmt_marks = st.number_input("Marks *", min_value=1, value=50, help="How many marks is this worth?")
    with col2:
        asmt_due = st.date_input("Due date (optional)", value=None)
    asmt_timed = st.checkbox("Timed (exam-like)", value=True,
                             help="Check for exams/quizzes, uncheck for assignments/projects")
    asmt_notes = st.text_input("Notes (optional)")

    col_cancel, col_submit = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True, key="asmt_cancel"):
            st.rerun()
    with col_submit:
        if st.button("Add Assessment", type="primary", use_container_width=True, key="asmt_submit"):
            if asmt_name.strip():
                execute_returning(
                    """INSERT INTO assessments(user_id, course_id, assessment_name, assessment_type, marks, due_date, is_timed, notes)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (user_id, course_id, asmt_name.strip(), asmt_type, asmt_marks,
                     str(asmt_due) if asmt_due else None, 1 if asmt_timed else 0, asmt_notes)
                )
                st.toast(f"Added: {asmt_name} ({asmt_marks} marks)")
                st.rerun()
            else:
                st.error("Please enter an assessment name.")

@st.dialog("Add Topic")
def add_topics_dialog():
    """Dialog for adding a new topic."""
    topic_name = st.text_input("Topic name *", placeholder="e.g., Supply and Demand")
    weight = st.number_input("Weight (points)", min_value=0, value=10,
                             help="Expected exam marks for this topic")
    notes = st.text_input("Notes (optional)")

    col_cancel, col_submit = st.columns(2)
    with col_cancel:
        if st.button("Cancel", use_container_width=True, key="topic_cancel"):
            st.rerun()
    with col_submit:
        if st.button("Add Topic", type="primary", use_container_width=True, key="topic_submit"):
            if topic_name.strip():
                execute_returning(
                    "INSERT INTO topics(user_id, course_id, topic_name, weight_points, notes) VALUES(?,?,?,?,?)",
                    (user_id, course_id, topic_name.strip(), weight, notes if notes else None)
                )
                st.toast(f"Added topic: {topic_name}")
                st.rerun()
            else:
                st.error("Please enter a topic name.")

# ============ SETUP BAR HELPER ============
def render_setup_bar(user_id: int, course_id: int):
    """Render a persistent setup bar with primary actions."""
    # Check if current course has exams
    course_exams = read_sql("SELECT COUNT(*) as cnt FROM exams WHERE user_id=? AND course_id=?",
                            (user_id, course_id))
    has_course_exams = course_exams.iloc[0]['cnt'] > 0 if not course_exams.empty else False

    cols = st.columns([1, 1, 4]) if has_course_exams else st.columns([1, 5])
    with cols[0]:
        if st.button("Add exam", key=f"setup_add_exam_{st.session_state.get('_setup_bar_key', 0)}", use_container_width=True):
            add_exam_dialog()
    if has_course_exams:
        with cols[1]:
            if st.button("Add assessment", key=f"setup_add_assessment_{st.session_state.get('_setup_bar_key', 0)}", use_container_width=True):
                add_assessment_dialog()

# ============ TABS ============
# Simplified 3-tab layout: Dashboard, Exams (setup), Study (log sessions)
tabs = st.tabs(["Dashboard", "Exams", "Study"])

# ============ DASHBOARD ============
with tabs[0]:
    today = date.today()

    # ============ EMPTY STATE CHECK ============
    total_exams_df = read_sql("SELECT COUNT(*) as cnt FROM exams WHERE user_id=?", (user_id,))
    has_exams = total_exams_df.iloc[0]['cnt'] > 0 if not total_exams_df.empty else False

    if not has_exams:
        # ============ EMPTY STATE UI ============
        st.markdown("")
        if render_empty_state(
            title="No exams yet",
            description="Add your first exam to start tracking your readiness and get personalized study recommendations.",
            button_label="Add exam",
            on_click_key="navigate_to_exams"
        ):
            add_exam_dialog()

    if has_exams:
        # ============ VIEW TOGGLE (GLOBAL vs COURSE) ============
        st.header("Dashboard")

        # ============ ONBOARDING CHECKLIST ============
        # Check setup completion for current course
        course_exam_count = read_sql("SELECT COUNT(*) as cnt FROM exams WHERE user_id=? AND course_id=?", (user_id, course_id))
        course_assessment_count = read_sql("SELECT COUNT(*) as cnt FROM assessments WHERE user_id=? AND course_id=?", (user_id, course_id))
        course_topic_count = read_sql("SELECT COUNT(*) as cnt FROM topics WHERE user_id=? AND course_id=?", (user_id, course_id))

        has_course_exams = course_exam_count.iloc[0]['cnt'] > 0 if not course_exam_count.empty else False
        has_course_assessments = course_assessment_count.iloc[0]['cnt'] > 0 if not course_assessment_count.empty else False
        has_course_topics = course_topic_count.iloc[0]['cnt'] > 0 if not course_topic_count.empty else False

        setup_incomplete = not (has_course_exams and has_course_assessments and has_course_topics)

        if setup_incomplete:
            # Inline setup checklist with direct dialog calls
            st.markdown("**Complete Setup**")
            setup_items = [
                ('Add exam', has_course_exams, 'checklist_exam'),
                ('Add assessment', has_course_assessments, 'checklist_assessment'),
                ('Add topics', has_course_topics, 'checklist_topics'),
            ]
            for label, done, key in setup_items:
                col1, col2 = st.columns([4, 1])
                with col1:
                    if done:
                        st.markdown(f":white_check_mark: ~~{label}~~")
                    else:
                        st.markdown(f":white_circle: {label}")
                with col2:
                    if not done:
                        if key == 'checklist_exam':
                            if st.button("Add", key=key, use_container_width=True):
                                add_exam_dialog()
                        elif key == 'checklist_assessment':
                            if st.button("Add", key=key, use_container_width=True):
                                add_assessment_dialog()
                        elif key == 'checklist_topics':
                            if st.button("Add", key=key, use_container_width=True):
                                add_topics_dialog()
            st.markdown("")

        # NOTE: Setup bar removed from Dashboard - setup actions only in Exams tab

        view_col1, view_col2 = st.columns([2, 1])
        with view_col1:
            dashboard_view = st.radio(
                "View:",
                options=["Global (All Courses)", f"Course ({selected_course})"],
                horizontal=True,
                key="dashboard_view"
            )

        is_global_view = "Global" in dashboard_view

        st.divider()

        # ============ GLOBAL VIEW ============
        if is_global_view:
            st.markdown("### All Courses Overview")

            # Get all courses
            all_courses = get_all_courses(user_id)

            if all_courses.empty:
                st.info("No courses yet. Select a course from the sidebar to get started.")
            else:
                # ============ SECTION 1: UPCOMING ASSESSMENTS ============
                st.header("Upcoming Assessments (Next 30 Days)")

                upcoming_assessments = get_all_upcoming_assessments(user_id, days_ahead=30)

                if not upcoming_assessments.empty:
                    # Format the table
                    assessment_display = []
                    for _, asmt in upcoming_assessments.iterrows():
                        due_date = pd.to_datetime(asmt['due_date']).date()
                        days_until = (due_date - today).days

                        if days_until <= 3:
                            urgency = "🔴"
                        elif days_until <= 7:
                            urgency = "🟡"
                        else:
                            urgency = "🟢"

                        assessment_display.append({
                            "": urgency,
                            "Course": asmt['course_name'],
                            "Assessment": asmt['assessment_name'],
                            "Type": asmt['assessment_type'],
                            "Marks": int(asmt['marks']),
                            "Due Date": due_date.strftime("%a %d/%m/%Y"),
                            "Days Left": days_until
                        })

                    assessment_df = pd.DataFrame(assessment_display)
                    st.dataframe(assessment_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No upcoming assessments in the next 30 days.")

                st.divider()

                # ============ SECTION 2: RECOMMENDED ACTIONS ============
                st.header("Recommended Actions (Top 10)")

                recommended_tasks = generate_recommended_tasks(user_id, course_id=None, max_tasks=10)

                if recommended_tasks:
                    # Display tasks as cards
                    for i, task in enumerate(recommended_tasks[:10]):
                        task_type_labels = {
                            'assessment_due': '[Due]',
                            'timed_attempt': '[Practice]',
                            'review_topic': '[Review]',
                            'do_exercises': '[Exercises]',
                            'setup_missing': '[Setup]'
                        }

                        label = task_type_labels.get(task['task_type'], '')
                        course_tag = f"**{task['course_name']}**"
                        time_info = f" · ~{task['est_minutes']}min" if task.get('est_minutes') else ""

                        st.markdown(f"{i+1}. {label} {task['title']} ({course_tag}){time_info}")
                        st.caption(f"   ↳ {task['detail']}")
                else:
                    st.info("All caught up! No urgent actions needed.")

                st.divider()

                # ============ SECTION 3: AT-RISK COURSES ============
                st.header("At-Risk Courses")

                at_risk = get_at_risk_courses(user_id, readiness_threshold=0.6, days_threshold=21)

                if at_risk:
                    risk_data = []
                    for course_snapshot in at_risk:
                        status_icons = {
                            'at_risk': '🔴',
                            'borderline': '🟡',
                            'on_track': '🟢',
                            'early_signal': '🟠'
                        }

                        risk_data.append({
                            "": status_icons.get(course_snapshot['status'], '⚪'),
                            "Course": course_snapshot['course_name'],
                            "Readiness": f"{course_snapshot['readiness_pct']:.0f}%",
                            "Predicted": f"{course_snapshot['predicted_marks']:.0f}/{course_snapshot['total_marks']}",
                            "Days Left": course_snapshot['days_left'] if course_snapshot['days_left'] else "—",
                            "Next Due": course_snapshot['next_assessment_name'] or "—"
                        })

                    risk_df = pd.DataFrame(risk_data)
                    st.dataframe(risk_df, use_container_width=True, hide_index=True)

                    st.caption("**Tip**: Switch to Course view to see detailed recommendations for each course.")
                else:
                    st.success("All courses are on track! Keep up the great work.")

                st.divider()

                # ============ SECTION 4: QUICK COURSE SUMMARY ============
                st.header("All Courses Summary")

                course_summaries = []
                for _, course in all_courses.iterrows():
                    cid = int(course['id'])
                    cname = course['course_name']

                    has_topics = get_course_topic_count(user_id, cid) > 0
                    has_assessments = get_course_assessment_count(user_id, cid) > 0

                    if has_topics:
                        # Compute snapshot
                        snapshot = compute_course_snapshot(user_id, cid)
                        if snapshot:
                            status_icons = {
                                'at_risk': '🔴',
                                'borderline': '🟡',
                                'on_track': '🟢',
                                'early_signal': '🟠'
                            }

                            course_summaries.append({
                                "": status_icons.get(snapshot['status'], '⚪'),
                                "Course": cname,
                                "Predicted": f"{snapshot['predicted_marks']:.0f}/{snapshot['total_marks']}",
                                "Target": f"{snapshot['target_marks']}",
                                "Readiness": f"{snapshot['readiness_pct']:.0f}%",
                                "Days Left": snapshot['days_left'] if snapshot['days_left'] else "—"
                            })
                    else:
                        course_summaries.append({
                            "": "⚙️",
                            "Course": cname,
                            "Predicted": "—",
                            "Target": "—",
                            "Readiness": "—",
                            "Days Left": "Setup needed"
                        })

                if course_summaries:
                    summary_df = pd.DataFrame(course_summaries)
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)

        # ============ COURSE VIEW ============
        else:
            st.markdown(f"### {selected_course} — Course Dashboard")

            # ============ PREREQUISITE GATES ============
            # Check setup completion for predictions
            prereq_step = get_next_prerequisite_step(user_id, course_id)

            # Gate 1: No assessments → show Setup required card
            if not has_course_assessments:
                st.markdown("")
                if render_empty_state(
                    title="Setup required",
                    description="Add assessments to see predictions. Assessments define what you're being graded on (exams, assignments, projects).",
                    button_label="Add assessment",
                    on_click_key="gate_add_assessment"
                ):
                    add_assessment_dialog()
                # Stop here - don't show predictions without assessments

            # Gate 2: Has assessments but no topics → show Setup required card
            elif not has_course_topics:
                st.markdown("")
                if render_empty_state(
                    title="Setup required",
                    description="Add topics to see predictions. Topics are the subjects you need to study for your assessments.",
                    button_label="Add topics",
                    on_click_key="gate_add_topics"
                ):
                    add_topics_dialog()
                # Stop here - don't show predictions without topics

            # Gate 3: All prerequisites met → show full dashboard
            else:
                # Get course total marks from assessments
                course_total_marks = get_course_total_marks(user_id, course_id)
                if course_total_marks == 0:
                    ensure_default_assessment(user_id, course_id)
                    course_total_marks = get_course_total_marks(user_id, course_id)

                # Get next due date from assessments (primary source)
                next_due, next_assessment_name, next_is_timed = get_next_due_date(user_id, course_id, today)

                # Fallback to exams table for backward compatibility
                exams_df = read_sql("SELECT * FROM exams WHERE user_id=? AND course_id=? ORDER BY exam_date",
                                    (user_id, course_id))

                # Determine tracking date and retake status
                if next_due:
                    # Use assessment due date
                    tracking_date = next_due
                    days_left = max((tracking_date - today).days, 0)
                    is_retake = not next_is_timed  # Non-timed assessments treated like retakes (no lecture requirement)
                    st.caption(f"Tracking: **{next_assessment_name}** (due {tracking_date.strftime('%d/%m/%Y')})")
                elif not exams_df.empty:
                    # Fallback to exam date
                    exam_options = exams_df.apply(lambda r: f"{r['exam_name']} ({r['exam_date']}){' [RETAKE]' if r.get('is_retake', 0) == 1 else ''}", axis=1).tolist()
                    selected_exam_idx = st.selectbox("Select exam to track", range(len(exam_options)), format_func=lambda i: exam_options[i])
                    exam_row = exams_df.iloc[selected_exam_idx]
                    tracking_date = pd.to_datetime(exam_row["exam_date"]).date()
                    days_left = max((tracking_date - today).days, 0)
                    is_retake = bool(exam_row.get("is_retake", 0))
                    next_assessment_name = exam_row["exam_name"]
                else:
                    # No due dates set — use defaults
                    tracking_date = None
                    days_left = 30  # Default for calculations
                    is_retake = False

                if is_retake:
                    st.info("**Non-timed assessment** — Lectures not included in readiness calculations.")

                topics_df = read_sql("SELECT id, topic_name, weight_points, notes FROM topics WHERE user_id=? AND course_id=? ORDER BY id",
                                     (user_id, course_id))
                upcoming_lectures = read_sql("""
                    SELECT * FROM scheduled_lectures
                    WHERE user_id=? AND course_id=? AND lecture_date >= ?
                    ORDER BY lecture_date LIMIT 10
                """, (user_id, course_id, str(today)))

                # Get timed attempts data for dashboard display
                timed_attempts_df = read_sql("""
                    SELECT * FROM timed_attempts
                    WHERE user_id=? AND course_id=?
                    ORDER BY attempt_date DESC
                """, (user_id, course_id))

                # Timed attempts stats
                recent_timed = timed_attempts_df[
                    pd.to_datetime(timed_attempts_df["attempt_date"]).dt.date >= (today - timedelta(days=14))
                ] if not timed_attempts_df.empty else pd.DataFrame()
                latest_timed_score = timed_attempts_df.iloc[0]["score_pct"] * 100 if not timed_attempts_df.empty else None
                timed_count_14d = len(recent_timed)
                # ============ USE CANONICAL SNAPSHOT FOR PREDICTIONS ============
                # This ensures At-Risk, All Courses Summary, and Course Dashboard
                # all show the SAME predicted values for the same course.
                snapshot = compute_course_snapshot(user_id, course_id, is_retake=is_retake)

                # Extract values from canonical snapshot
                pred_marks = snapshot['predicted_marks']
                retention_pct = snapshot['readiness_pct'] / 100  # Convert back to 0-1 for display compatibility
                coverage_pct = snapshot['coverage_pct'] / 100
                practice_blend = snapshot['practice_blend'] / 100

                # Show actual marks breakdown if applicable
                if snapshot['has_actual_marks']:
                    actual_marks_earned = snapshot['actual_marks_earned']
                    actual_marks_possible = snapshot['actual_marks_possible']
                    remaining_marks = total_marks - actual_marks_possible

                    if remaining_marks > 0:
                        predicted_remaining = pred_marks - actual_marks_earned
                        actual_pct = (actual_marks_earned / actual_marks_possible * 100) if actual_marks_possible > 0 else 0
                        st.info(f"**Grade Breakdown**: Actual: {int(actual_marks_earned)}/{int(actual_marks_possible)} ({actual_pct:.0f}%) + Predicted: {predicted_remaining:.1f}/{remaining_marks}")
                    else:
                        actual_pct = (actual_marks_earned / total_marks * 100) if total_marks > 0 else 0
                        st.success(f"**All assessments completed!** Final grade: {int(actual_marks_earned)}/{total_marks} ({actual_pct:.0f}%)")

                # Show prediction mode indicator
                if practice_blend > 0:
                    blend_pct = int(practice_blend * 100)
                    if blend_pct < 25:
                        blend_desc = "**Study Focus** — Predictions weighted toward mastery & review"
                    elif blend_pct < 50:
                        blend_desc = "**Balanced** — Mixing mastery with practice performance"
                    else:
                        blend_desc = "**Practice Focus** — Predictions weighted toward timed attempts"
                    st.caption(f"{blend_desc} (Practice weight: {blend_pct}%)")

                st.markdown("")

                # ============ KPI CARDS ROW ============
                maturity_tier = snapshot.get('maturity_tier', 'MID')
                maturity_reason = snapshot.get('maturity_reason', '')
                confidence_label = {"EARLY": "Early", "MID": "Mid", "LATE": "Late"}.get(maturity_tier, "Mid")

                # Determine color variants based on status
                status = snapshot['status']
                status_variant_map = {
                    'on_track': 'success',
                    'borderline': 'warning',
                    'at_risk': 'danger',
                    'early_signal': 'orange'
                }
                predicted_variant = status_variant_map.get(status)

                # Readiness color based on percentage
                readiness_val = retention_pct * 100
                if readiness_val >= 70:
                    readiness_variant = 'success'
                elif readiness_val >= 40:
                    readiness_variant = 'warning'
                else:
                    readiness_variant = 'danger'

                # Days left color based on urgency
                if tracking_date and days_left <= 7:
                    days_variant = 'danger'
                elif tracking_date and days_left <= 14:
                    days_variant = 'warning'
                elif tracking_date and days_left <= 30:
                    days_variant = 'orange'
                else:
                    days_variant = 'info'

                kpi_metrics = [
                    {
                        'label': 'Predicted',
                        'value': f"{pred_marks:.0f}/{total_marks}",
                        'subtext': f"Target: {target_marks}",
                        'variant': predicted_variant
                    },
                    {
                        'label': 'Readiness',
                        'value': f"{retention_pct*100:.0f}%",
                        'subtext': f"Confidence: {confidence_label}",
                        'variant': readiness_variant
                    },
                    {
                        'label': 'Days Left',
                        'value': f"{days_left}" if tracking_date else "N/A",
                        'subtext': next_assessment_name[:20] + "..." if next_assessment_name and len(next_assessment_name) > 20 else (next_assessment_name or "No due date"),
                        'variant': days_variant if tracking_date else None
                    },
                ]
                render_kpi_row(kpi_metrics)

                # Status badge (rendered separately for HTML badge styling)
                st.markdown(f"""
                <div style="text-align: center; margin-top: 0.75rem; margin-bottom: 1rem;">
                    {status_badge(snapshot['status'])}
                    <div class="confidence-indicator">{maturity_reason}</div>
                </div>
                """, unsafe_allow_html=True)

                # ============ COMPUTE TOPICS_SCORED FOR RECOMMENDATIONS/STUDY PLAN ============
                # We still need topics_scored for the recommendation engine and study plan
                mastery_data = []
                for _, row in topics_df.iterrows():
                    m, last_act, ex_cnt, st_cnt, lec_cnt, timed_sig, timed_cnt = compute_mastery(int(row["id"]), today, is_retake)
                    mastery_data.append({
                        "id": row["id"],
                        "topic_name": row["topic_name"],
                        "weight_points": row["weight_points"],
                        "mastery": round(m, 2),
                        "last_activity": last_act,
                        "exercises": ex_cnt,
                        "study_sessions": st_cnt,
                        "lectures": lec_cnt if not is_retake else 0,
                        "timed_signal": timed_sig,
                        "timed_count": timed_cnt
                    })

                topics_with_mastery = pd.DataFrame(mastery_data)

                # DIRECT CALCULATION - bypassing compute_readiness to fix 1% bug
                # Readiness = mastery / 5.0 (mastery is 0-5 scale)
                topics_scored = topics_with_mastery.copy()
                topics_scored["readiness"] = topics_scored["mastery"] / 5.0
                topics_scored["expected_points"] = topics_scored["weight_points"] * topics_scored["readiness"]
                # Compute gap_score BEFORE creating topics_display (gap = weight * (1 - readiness))
                topics_scored["gap_score"] = topics_scored["weight_points"] * (1.0 - topics_scored["readiness"])
                weight_sum = float(topics_scored["weight_points"].sum()) if not topics_scored.empty else 0.0
                expected_sum = float(topics_scored["expected_points"].sum()) if not topics_scored.empty else 0.0

                # Create display version with readiness as percentage string
                topics_display = topics_scored.copy()
                topics_display["Readiness %"] = topics_display["readiness"].apply(lambda x: f"{int(x * 100)}%")
                topics_display["last_activity"] = topics_display["last_activity"].apply(
                    lambda x: x.strftime("%d.%m.%Y") if x is not None else "—"
                )

                # ============ PER-ASSESSMENT BREAKDOWN ============
                section_header("Assessment Breakdown")
                card_start()

                all_assessments = read_sql("""
                    SELECT id, assessment_name, assessment_type, marks, actual_marks, progress_pct, due_date, is_timed
                    FROM assessments WHERE user_id=? AND course_id=? ORDER BY due_date, id
                """, (user_id, course_id))

                if not all_assessments.empty:
                    # Calculate predicted marks per assessment
                    avg_readiness = retention_pct if weight_sum > 0 else 0.5

                    breakdown_data = []
                    for _, asmt in all_assessments.iterrows():
                        asmt_marks = asmt["marks"]
                        actual = asmt["actual_marks"]
                        progress = asmt["progress_pct"] or 0
                        is_timed = asmt["is_timed"] == 1

                        if pd.notna(actual):
                            # Already completed
                            predicted = actual
                            status_icon = "[Done]"
                            status_text = f"Completed: {int(actual)}/{asmt_marks}"
                        elif is_timed:
                            # Exam - use readiness
                            predicted = asmt_marks * avg_readiness
                            status_icon = "[Exam]"
                            pct = int(avg_readiness * 100)
                            status_text = f"Predicted: {predicted:.0f}/{asmt_marks} ({pct}%)"
                        else:
                            # Assignment - use progress + readiness blend
                            if progress >= 100:
                                predicted = asmt_marks * avg_readiness
                                status_icon = "[Ready]"
                                status_text = f"Ready to submit: ~{predicted:.0f}/{asmt_marks}"
                            else:
                                # Partial progress - scale prediction
                                progress_factor = progress / 100
                                predicted = asmt_marks * (0.5 + 0.5 * progress_factor) * avg_readiness
                                status_icon = "[WIP]"
                                status_text = f"In progress ({progress}%): ~{predicted:.0f}/{asmt_marks}"

                        breakdown_data.append({
                            "": status_icon,
                            "Assessment": asmt["assessment_name"],
                            "Type": asmt["assessment_type"],
                            "Marks": f"{int(asmt_marks)}",
                            "Status": status_text
                        })

                    breakdown_df = pd.DataFrame(breakdown_data)
                    st.dataframe(breakdown_df, use_container_width=True, hide_index=True)

                card_end()

                # ============ GATED: RECOMMENDED ACTIONS ============
                # Only show recommendations when prerequisites are complete
                if prereq_step is None:
                    section_header("Next Actions")
                    card_start()

                    # Generate recommended tasks for this course (gap_score already computed above)
                    course_tasks = generate_recommended_tasks(user_id, course_id=course_id, max_tasks=5)

                    if course_tasks:
                        render_action_list(course_tasks, max_items=5)
                    else:
                        # Fallback to old recommendations if task generator returns nothing
                        recs = generate_recommendations(topics_scored, upcoming_lectures, days_left, today, is_retake)
                        if recs:
                            for rec in recs:
                                st.markdown(f"- {rec}")
                        else:
                            st.markdown("All caught up! No urgent actions needed.")

                    card_end()
                # ============ TOP GAPS CARD ============
                section_header("Top Gaps")
                card_start()
                # Defensive: ensure gap_score exists (should already be computed, but fallback if not)
                if "gap_score" not in topics_display.columns:
                    topics_display["gap_score"] = topics_display.get("weight_points", 0) * (1.0 - topics_display.get("readiness", 0))
                gaps = topics_display.sort_values("gap_score", ascending=False).head(6)
                st.dataframe(
                    gaps[["topic_name", "weight_points", "mastery", "exercises", "study_sessions", "Readiness %"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "topic_name": st.column_config.TextColumn("Topic"),
                        "weight_points": st.column_config.NumberColumn("Weight"),
                        "mastery": st.column_config.ProgressColumn("Mastery", format="%.1f/5", min_value=0, max_value=5),
                        "exercises": st.column_config.NumberColumn("Exercises"),
                        "study_sessions": st.column_config.NumberColumn("Sessions"),
                        "Readiness %": st.column_config.TextColumn("Readiness"),
                    }
                )
                card_end()

                # ============ STUDY PLAN GENERATOR ============
                section_header("7-Day Study Plan")
                card_start()

                # Get settings from session state
                hours_per_week = st.session_state.get("hours_per_week", 10)
                session_length = st.session_state.get("session_length", 60)

                # Calculate total sessions available
                total_mins_per_week = hours_per_week * 60
                num_sessions = max(1, total_mins_per_week // session_length)

                # Determine session types based on days_left
                timed_sessions = 1 if days_left < 30 else 0
                mixed_sessions = 2 if days_left < 21 else (1 if days_left < 45 else 0)
                topic_sessions = max(1, num_sessions - timed_sessions - mixed_sessions)

                # Get topics sorted by gap_score (defensive check)
                if "gap_score" not in topics_scored.columns:
                    topics_scored["gap_score"] = topics_scored["weight_points"] * (1.0 - topics_scored["readiness"])
                gaps_for_plan = topics_scored.sort_values("gap_score", ascending=False).copy()

                if not gaps_for_plan.empty and gaps_for_plan["gap_score"].sum() > 0:
                    # Normalize gap_scores to allocate sessions proportionally
                    gaps_for_plan["session_share"] = gaps_for_plan["gap_score"] / gaps_for_plan["gap_score"].sum()
                    gaps_for_plan["allocated_sessions"] = (gaps_for_plan["session_share"] * topic_sessions).round().astype(int)

                    # Ensure at least 1 session for top gaps, redistribute if needed
                    if gaps_for_plan["allocated_sessions"].sum() < topic_sessions:
                        # Add remaining to top gap topics
                        remaining = topic_sessions - gaps_for_plan["allocated_sessions"].sum()
                        for i in range(int(remaining)):
                            idx = i % len(gaps_for_plan)
                            gaps_for_plan.iloc[idx, gaps_for_plan.columns.get_loc("allocated_sessions")] += 1

                    # Build the plan
                    plan = []
                    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    session_idx = 0

                    # Distribute topic review sessions
                    for _, row in gaps_for_plan.iterrows():
                        topic_name = row["topic_name"]
                        mastery = row["mastery"]
                        sessions_for_topic = int(row["allocated_sessions"])

                        for _ in range(sessions_for_topic):
                            if session_idx >= num_sessions:
                                break
                            day = day_names[session_idx % 7]
                            # Determine session type based on mastery
                            if mastery < 2:
                                session_type = "Review"
                            elif mastery < 4:
                                session_type = "Exercises"
                            else:
                                session_type = "Refresh"

                            plan.append({
                                "Day": day,
                                "Topic": topic_name,
                                "Type": session_type,
                                "Duration": f"{session_length} mins"
                            })
                            session_idx += 1

                    # Add mixed practice sessions
                    for i in range(mixed_sessions):
                        if session_idx >= num_sessions:
                            break
                        day = day_names[session_idx % 7]
                        top_3_topics = ", ".join(gaps_for_plan.head(3)["topic_name"].tolist())
                        plan.append({
                            "Day": day,
                            "Topic": f"Mixed: {top_3_topics}",
                            "Type": "Mixed Practice",
                            "Duration": f"{session_length} mins"
                        })
                        session_idx += 1

                    # Add timed attempt sessions
                    for i in range(timed_sessions):
                        if session_idx >= num_sessions:
                            break
                        day = day_names[session_idx % 7]
                        plan.append({
                            "Day": day,
                            "Topic": "Full Paper / Past Exam",
                            "Type": "Timed Attempt",
                            "Duration": f"{session_length * 2} mins"  # Timed attempts are longer
                        })
                        session_idx += 1

                    # Sort by day order
                    day_order = {d: i for i, d in enumerate(day_names)}
                    plan_df = pd.DataFrame(plan)
                    if not plan_df.empty:
                        plan_df["day_order"] = plan_df["Day"].map(day_order)
                        plan_df = plan_df.sort_values("day_order").drop("day_order", axis=1).reset_index(drop=True)

                        # Display the plan
                        st.dataframe(
                            plan_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Day": st.column_config.TextColumn("Day"),
                                "Topic": st.column_config.TextColumn("Topic"),
                                "Type": st.column_config.TextColumn("Session Type"),
                                "Duration": st.column_config.TextColumn("Duration"),
                            }
                        )

                        # Plan summary
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.caption(f"**{len(plan_df)} sessions** this week")
                        with col2:
                            total_study_time = sum([int(d.split()[0]) for d in plan_df["Duration"]])
                            st.caption(f"**{total_study_time // 60}h {total_study_time % 60}m** total")
                        with col3:
                            st.caption(f"Prioritizing: **{gaps_for_plan.iloc[0]['topic_name']}**")

                        # Export button
                        csv_data = plan_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "Export Plan as CSV",
                            csv_data,
                            f"study_plan_{selected_course.replace(' ', '_')}.csv",
                            "text/csv",
                            key="download_study_plan"
                        )
                else:
                    st.markdown("Add topics with weights to generate a study plan.")

                card_end()

                if not is_retake and not upcoming_lectures.empty:
                    section_header("Upcoming Lectures")
                    card_start()
                    upcoming_lectures["lecture_date"] = pd.to_datetime(upcoming_lectures["lecture_date"])
                    st.dataframe(
                        upcoming_lectures[["lecture_date", "lecture_time", "topics_planned"]].head(5),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "lecture_date": st.column_config.DateColumn("Date", format="ddd DD/MM"),
                            "lecture_time": st.column_config.TextColumn("Time"),
                            "topics_planned": st.column_config.TextColumn("Topics"),
                        }
                    )
                    card_end()

                section_header("All Topics")
                card_start()
                if is_retake:
                    topics_display_cols = ["topic_name", "weight_points", "mastery", "last_activity", "exercises", "study_sessions", "Readiness %"]
                else:
                    topics_display_cols = ["topic_name", "weight_points", "mastery", "last_activity", "exercises", "study_sessions", "lectures", "Readiness %"]
                st.dataframe(
                    topics_display[topics_display_cols],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "topic_name": st.column_config.TextColumn("Topic"),
                        "weight_points": st.column_config.NumberColumn("Weight"),
                        "mastery": st.column_config.ProgressColumn("Mastery", format="%.1f/5", min_value=0, max_value=5),
                        "last_activity": st.column_config.TextColumn("Last Activity"),
                        "exercises": st.column_config.NumberColumn("Exercises"),
                        "study_sessions": st.column_config.NumberColumn("Sessions"),
                        "lectures": st.column_config.NumberColumn("Lectures"),
                        "Readiness %": st.column_config.TextColumn("Readiness"),
                    }
                )
                card_end()

# ============ EXAMS TAB (Setup) ============
# Contains: Exams (main), Assessments, Topics, Import Topics
with tabs[1]:
    st.header("Exam Setup")

    # Setup bar for quick actions
    st.session_state._setup_bar_key = 1
    render_setup_bar(user_id, course_id)

    st.caption("Set up your exams, assessments, and topics for this course.")

    # ============ EXAMS SECTION (Main - always visible) ============
    st.write("### Add Exam")

    # Show post-exam-creation success message and next step guidance
    if "exam_created_msg" in st.session_state:
        st.success(st.session_state.pop("exam_created_msg"))
        next_step = st.session_state.pop("post_exam_next_step", None)
        if next_step == "assessments":
            col_msg, col_btn = st.columns([3, 1])
            with col_msg:
                st.info("**Next step:** Add an assessment to define what you're being graded on.")
            with col_btn:
                if st.button("Add assessment", key="post_exam_add_assessment", type="primary"):
                    add_assessment_dialog()
        elif next_step == "topics":
            st.info("**Next step:** Expand Topics below to add what you need to study.")

    exams_df = read_sql("SELECT * FROM exams WHERE user_id=? AND course_id=? ORDER BY exam_date",
                        (user_id, course_id))

    with st.form("add_exam"):
        col1, col2, col3 = st.columns(3)
        with col1:
            exam_name = st.text_input("Exam name", placeholder="e.g., Midterm, Final Exam")
        with col2:
            exam_date_input = st.date_input("Exam date", value=date.today() + timedelta(days=60))
        with col3:
            exam_marks = st.number_input("Marks", min_value=1, value=100, help="How many marks is this exam worth?")

        is_retake_input = st.checkbox("This is a retake (no lectures)", value=False,
                                      help="Retake exams exclude lectures from readiness calculations")

        if st.form_submit_button("➕ Add Exam", type="primary"):
            if exam_name.strip():
                execute_returning("INSERT INTO exams(user_id, course_id, exam_name, exam_date, marks, is_retake) VALUES(?,?,?,?,?,?)",
                                 (user_id, course_id, exam_name.strip(), str(exam_date_input), exam_marks, 1 if is_retake_input else 0))

                # Store success message for after rerun
                st.session_state.exam_created_msg = f"Exam '{exam_name}' created!"

                # Check next setup step and route accordingly
                assessment_count = read_sql("SELECT COUNT(*) as cnt FROM assessments WHERE user_id=? AND course_id=?", (user_id, course_id))
                has_assessments = assessment_count.iloc[0]['cnt'] > 0 if not assessment_count.empty else False

                if not has_assessments:
                    # Route to assessments
                    st.session_state.expand_assessments = True
                    st.session_state.post_exam_next_step = "assessments"
                else:
                    # Check for topics
                    topic_count = read_sql("SELECT COUNT(*) as cnt FROM topics WHERE user_id=? AND course_id=?", (user_id, course_id))
                    has_topics = topic_count.iloc[0]['cnt'] > 0 if not topic_count.empty else False

                    if not has_topics:
                        # Route to topics
                        st.session_state.expand_topics = True
                        st.session_state.post_exam_next_step = "topics"

                st.rerun()
            else:
                st.error("Please enter an exam name.")

    if not exams_df.empty:
        st.divider()

        # Calculate completed vs pending
        if "actual_marks" not in exams_df.columns:
            exams_df["actual_marks"] = None
        completed_count = exams_df["actual_marks"].notna().sum()
        total_exam_marks = exams_df["marks"].sum() if "marks" in exams_df.columns else 0
        actual_earned = exams_df["actual_marks"].fillna(0).sum()

        st.write(f"**Your Exams ({len(exams_df)} total):**")
        if completed_count > 0:
            st.caption(f"{completed_count} completed — Actual marks earned: **{int(actual_earned)}**")

        exams_df["exam_date"] = pd.to_datetime(exams_df["exam_date"])
        exams_df["delete"] = False

        edited_exams = st.data_editor(
            exams_df[["id", "exam_name", "exam_date", "marks", "actual_marks", "is_retake", "delete"]],
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "exam_name": st.column_config.TextColumn("Exam Name"),
                "exam_date": st.column_config.DateColumn("Date"),
                "marks": st.column_config.NumberColumn("Max Marks", min_value=1),
                "actual_marks": st.column_config.NumberColumn("Actual Marks", min_value=0, help="Enter your score once completed"),
                "is_retake": st.column_config.CheckboxColumn("Retake?"),
                "delete": st.column_config.CheckboxColumn("Delete?")
            },
            use_container_width=True,
            hide_index=True,
            key="exams_editor"
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Exam Changes"):
                for _, row in edited_exams.iterrows():
                    if not row["delete"]:
                        actual = int(row["actual_marks"]) if pd.notna(row["actual_marks"]) else None
                        execute(
                            "UPDATE exams SET exam_name=?, exam_date=?, marks=?, actual_marks=?, is_retake=? WHERE id=? AND user_id=?",
                            (row["exam_name"], pd.to_datetime(row["exam_date"]).strftime("%Y-%m-%d"),
                             int(row["marks"]), actual, 1 if row["is_retake"] else 0, int(row["id"]), user_id)
                        )
                st.success("Exams updated!")
                st.rerun()
        with col2:
            if st.button("Delete Selected Exams"):
                to_delete = edited_exams[edited_exams["delete"] == True]["id"].tolist()
                if to_delete:
                    for eid in to_delete:
                        execute("DELETE FROM exams WHERE id=? AND user_id=?", (int(eid), user_id))
                    st.success(f"Deleted {len(to_delete)} exam(s)!")
                    st.rerun()

    st.divider()

    # ============ ASSESSMENTS EXPANDER ============
    # Check if we should expand (from setup bar navigation)
    expand_assessments = st.session_state.pop("expand_assessments", False)
    with st.expander("Assessments", expanded=expand_assessments):
        st.caption("Define exams, assignments, projects, and quizzes. Total marks = sum of all assessments.")

        # Ensure default assessment exists
        ensure_default_assessment(user_id, course_id)

        # Add new assessment form
        st.write("**Add New Assessment:**")
        with st.form("add_assessment"):
            col1, col2, col3 = st.columns(3)
            with col1:
                asmt_name = st.text_input("Assessment name *", placeholder="e.g., Midterm Exam")
                asmt_type = st.selectbox("Type", ["Exam", "Assignment", "Project", "Quiz", "Other"])
            with col2:
                asmt_marks = st.number_input("Marks *", min_value=1, value=50, help="How many marks is this worth?")
                asmt_due = st.date_input("Due date (optional)", value=None)
            with col3:
                asmt_timed = st.checkbox("Timed (exam-like)", value=True,
                                         help="Check for exams/quizzes, uncheck for assignments/projects")
                asmt_notes = st.text_input("Notes (optional)")

            if st.form_submit_button("➕ Add Assessment", type="primary"):
                if asmt_name.strip():
                    execute_returning(
                        """INSERT INTO assessments(user_id, course_id, assessment_name, assessment_type, marks, due_date, is_timed, notes)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (user_id, course_id, asmt_name.strip(), asmt_type, asmt_marks,
                         str(asmt_due) if asmt_due else None, 1 if asmt_timed else 0, asmt_notes)
                    )
                    st.success(f"Added: {asmt_name} ({asmt_marks} marks)")
                    st.rerun()
                else:
                    st.error("Please enter an assessment name.")

        st.divider()

        # Display existing assessments
        assessments_df = read_sql("""
            SELECT id, assessment_name, assessment_type, marks, actual_marks, progress_pct, due_date, is_timed, notes
            FROM assessments WHERE user_id=? AND course_id=? ORDER BY due_date, id
        """, (user_id, course_id))

        if not assessments_df.empty:
            # Calculate completed vs pending
            completed_count = assessments_df["actual_marks"].notna().sum()
            total_marks_asmt = assessments_df["marks"].sum()
            actual_earned_asmt = assessments_df["actual_marks"].fillna(0).sum()

            st.write(f"**Your Assessments ({len(assessments_df)} total, {total_marks_asmt} marks possible):**")
            if completed_count > 0:
                st.caption(f"{completed_count} completed — Actual marks earned: **{int(actual_earned_asmt)}**")

            # Convert date for display
            assessments_df["due_date"] = pd.to_datetime(assessments_df["due_date"], errors="coerce")
            assessments_df["delete"] = False
            # Ensure progress_pct has default value
            if "progress_pct" not in assessments_df.columns:
                assessments_df["progress_pct"] = 0
            assessments_df["progress_pct"] = assessments_df["progress_pct"].fillna(0).astype(int)

            edited_assessments = st.data_editor(
                assessments_df[["id", "assessment_name", "assessment_type", "marks", "actual_marks", "progress_pct", "due_date", "is_timed", "notes", "delete"]],
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "assessment_name": st.column_config.TextColumn("Name"),
                    "assessment_type": st.column_config.SelectboxColumn("Type", options=["Exam", "Assignment", "Project", "Quiz", "Other"]),
                    "marks": st.column_config.NumberColumn("Max Marks", min_value=1),
                    "actual_marks": st.column_config.NumberColumn("Actual Marks", min_value=0, help="Enter your score once completed"),
                    "progress_pct": st.column_config.ProgressColumn("Progress %", format="%d%%", min_value=0, max_value=100, help="Work progress (for assignments)"),
                    "due_date": st.column_config.DateColumn("Due Date"),
                    "is_timed": st.column_config.CheckboxColumn("Timed?"),
                    "notes": st.column_config.TextColumn("Notes"),
                    "delete": st.column_config.CheckboxColumn("Delete?")
                },
                use_container_width=True,
                hide_index=True,
                key="assessments_editor"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Save Assessment Changes"):
                    for _, row in edited_assessments.iterrows():
                        if not row["delete"]:
                            due_str = str(row["due_date"].date()) if pd.notna(row["due_date"]) else None
                            actual = int(row["actual_marks"]) if pd.notna(row["actual_marks"]) else None
                            progress = int(row["progress_pct"]) if pd.notna(row["progress_pct"]) else 0
                            execute(
                                """UPDATE assessments SET assessment_name=?, assessment_type=?, marks=?,
                                   actual_marks=?, progress_pct=?, due_date=?, is_timed=?, notes=? WHERE id=? AND user_id=?""",
                                (row["assessment_name"], row["assessment_type"], int(row["marks"]),
                                 actual, progress, due_str, 1 if row["is_timed"] else 0, row["notes"], int(row["id"]), user_id)
                            )
                    st.success("Changes saved!")
                    st.rerun()
            with col2:
                if st.button("Delete Selected Assessments"):
                    to_delete = edited_assessments[edited_assessments["delete"] == True]["id"].tolist()
                    if to_delete:
                        for aid in to_delete:
                            execute("DELETE FROM assessments WHERE id=? AND user_id=?", (int(aid), user_id))
                        st.success(f"Deleted {len(to_delete)} assessment(s)!")
                        st.rerun()
        
        # ============ ASSIGNMENT WORK TRACKING ============
        st.divider()
        st.subheader("Log Assignment Work")
        st.caption("Track work sessions for assignments and projects to monitor progress.")
        
        # Get non-timed assessments (assignments/projects)
        assignment_options = assessments_df[assessments_df["is_timed"] == 0][["id", "assessment_name"]].values.tolist()
        
        if assignment_options:
            with st.form("log_assignment_work"):
                col1, col2 = st.columns(2)
                with col1:
                    work_assessment = st.selectbox(
                        "Select Assignment/Project",
                        options=[a[0] for a in assignment_options],
                        format_func=lambda x: next((a[1] for a in assignment_options if a[0] == x), str(x))
                    )
                    work_date = st.date_input("Date", value=date.today())
                with col2:
                    work_duration = st.number_input("Duration (minutes)", min_value=5, value=60, step=15)
                    work_type = st.selectbox("Work Type", ["Research", "Writing", "Coding", "Review", "Editing", "Other"])
                
                work_desc = st.text_input("Description (optional)", placeholder="What did you work on?")
                work_progress = st.slider("Progress added (%)", min_value=0, max_value=50, value=10, 
                                         help="How much progress did this session add?")
                
                if st.form_submit_button("Log Work Session", type="primary"):
                    execute_returning(
                        """INSERT INTO assignment_work(user_id, assessment_id, work_date, duration_mins, work_type, description, progress_added)
                           VALUES(?,?,?,?,?,?,?)""",
                        (user_id, work_assessment, str(work_date), work_duration, work_type, work_desc, work_progress)
                    )
                    # Update assessment progress
                    current_progress = fetchone("SELECT progress_pct FROM assessments WHERE id=?", (work_assessment,))
                    new_progress = min(100, (current_progress[0] or 0) + work_progress)
                    execute("UPDATE assessments SET progress_pct=? WHERE id=? AND user_id=?", 
                           (new_progress, work_assessment, user_id))
                    st.success(f"Work logged! Progress updated to {new_progress}%")
                    st.rerun()
            
            # Show work history
            work_history = read_sql("""
                SELECT aw.id, a.assessment_name, aw.work_date, aw.duration_mins, aw.work_type, aw.description, aw.progress_added
                FROM assignment_work aw
                JOIN assessments a ON aw.assessment_id = a.id
                WHERE aw.user_id=? AND a.course_id=?
                ORDER BY aw.work_date DESC
                LIMIT 10
            """, (user_id, course_id))
            
            if not work_history.empty:
                st.write("**Recent Work Sessions:**")
                total_hours = work_history["duration_mins"].sum() / 60
                st.caption(f"Total time logged: **{total_hours:.1f} hours**")
                st.dataframe(
                    work_history[["assessment_name", "work_date", "duration_mins", "work_type", "description", "progress_added"]],
                    column_config={
                        "assessment_name": "Assignment",
                        "work_date": "Date",
                        "duration_mins": st.column_config.NumberColumn("Minutes"),
                        "work_type": "Type",
                        "description": "Description",
                        "progress_added": st.column_config.NumberColumn("Progress +%")
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Add non-timed assessments (Assignments/Projects) above to track work progress.")
        else:
            st.info("No assessments yet. Add your first one above!")

    # ============ TOPICS EXPANDER ============
    # Check if we should expand (from checklist navigation)
    expand_topics = st.session_state.pop("expand_topics", False)
    with st.expander("Topics", expanded=expand_topics):
        st.caption("Add topics covered in this course. Weight = expected exam marks for this topic.")

        topics_df_exp = read_sql("SELECT id, topic_name, weight_points, notes FROM topics WHERE user_id=? AND course_id=? ORDER BY id",
                             (user_id, course_id))

        with st.form("add_topic_exp"):
            col1, col2 = st.columns([3, 1])
            with col1:
                topic_name_exp = st.text_input("Topic name", placeholder="e.g., Supply and Demand")
            with col2:
                weight_exp = st.number_input("Weight (points)", min_value=0, value=10)

            if st.form_submit_button("Add Topic"):
                if topic_name_exp.strip():
                    execute_returning("INSERT INTO topics(user_id, course_id, topic_name, weight_points) VALUES(?,?,?,?)",
                                     (user_id, course_id, topic_name_exp.strip(), weight_exp))
                    st.success("Topic added!")
                    st.rerun()

        if not topics_df_exp.empty:
            st.write("**Existing Topics:**")
            edited_topics = st.data_editor(
                topics_df_exp,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "topic_name": st.column_config.TextColumn("Topic Name", width="large"),
                    "weight_points": st.column_config.NumberColumn("Weight", min_value=0),
                    "notes": st.column_config.TextColumn("Notes"),
                },
                use_container_width=True,
                hide_index=True,
                key="topics_editor"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Save Topic Changes"):
                    for _, r in edited_topics.iterrows():
                        if pd.notna(r["id"]):
                            execute("UPDATE topics SET topic_name=?, weight_points=?, notes=? WHERE id=? AND user_id=?",
                                   (r["topic_name"], float(r["weight_points"]), r.get("notes"), int(r["id"]), user_id))
                    st.success("Topics updated!")
                    st.rerun()
            with col2:
                topic_to_delete = st.selectbox("Delete topic", topics_df_exp["topic_name"].tolist(), key="del_topic")
                if st.button("Delete Selected Topic"):
                    topic_id_del = topics_df_exp.loc[topics_df_exp["topic_name"] == topic_to_delete, "id"].iloc[0]
                    execute("DELETE FROM study_sessions WHERE topic_id=?", (int(topic_id_del),))
                    execute("DELETE FROM exercises WHERE topic_id=?", (int(topic_id_del),))
                    execute("DELETE FROM topics WHERE id=? AND user_id=?", (int(topic_id_del), user_id))
                    st.success("Topic and related data deleted!")
                    st.rerun()

    # ============ IMPORT TOPICS EXPANDER ============
    with st.expander("Import Topics from PDF", expanded=False):
        st.caption("Upload lecture slide PDFs to automatically extract topic names.")

        if not HAS_PYMUPDF:
            st.error("PDF extraction requires PyMuPDF. Install with: `pip install pymupdf`")
        else:
            # Initialize session state for imported topics
            if "imported_topics" not in st.session_state:
                st.session_state.imported_topics = None
            if "import_stats" not in st.session_state:
                st.session_state.import_stats = None

            # File uploader
            st.write("**Step 1: Upload PDF Files**")
            uploaded_files = st.file_uploader(
                "Select lecture slide PDFs",
                type=["pdf"],
                accept_multiple_files=True,
                help="Upload one or more PDF files containing lecture slides"
            )

            if uploaded_files:
                st.caption(f"{len(uploaded_files)} file(s) selected")

                # SECURITY: File size validation
                from security import MAX_PDF_SIZE, MAX_TOTAL_UPLOAD_SIZE, validate_pdf_header, sanitize_filename
                max_file_mb = MAX_PDF_SIZE / (1024 * 1024)
                max_total_mb = MAX_TOTAL_UPLOAD_SIZE / (1024 * 1024)

                # Check file sizes before processing
                total_size = 0
                file_errors = []
                for f in uploaded_files:
                    f.seek(0, 2)  # Seek to end
                    file_size = f.tell()
                    f.seek(0)  # Reset to start
                    total_size += file_size

                    if file_size > MAX_PDF_SIZE:
                        safe_name = sanitize_filename(f.name)
                        file_errors.append(f"{safe_name}: {file_size / (1024*1024):.1f}MB exceeds {max_file_mb:.0f}MB limit")

                if total_size > MAX_TOTAL_UPLOAD_SIZE:
                    file_errors.append(f"Total upload size {total_size / (1024*1024):.1f}MB exceeds {max_total_mb:.0f}MB limit")

                if file_errors:
                    for err in file_errors:
                        st.error(err)
                else:
                    # Extract topics button
                    if st.button("Extract Topics", type="primary"):
                        with st.spinner("Extracting topics from PDFs..."):
                            # Validate PDF headers and read files
                            pdf_files = []
                            validation_errors = []
                            for f in uploaded_files:
                                content = f.read()
                                if not validate_pdf_header(content):
                                    safe_name = sanitize_filename(f.name)
                                    validation_errors.append(f"{safe_name}: Invalid PDF file")
                                else:
                                    pdf_files.append((content, sanitize_filename(f.name)))
                                f.seek(0)

                            if validation_errors:
                                for err in validation_errors:
                                    st.error(err)
                            elif pdf_files:
                                try:
                                    candidates, stats = extract_and_process_topics(pdf_files)
                                    st.session_state.imported_topics = candidates
                                    st.session_state.import_stats = stats
                                    st.success("Extraction complete!")
                                except Exception as e:
                                    st.error(f"Error extracting topics: {e}")
                                    st.session_state.imported_topics = None

            # Show extraction results
            if st.session_state.imported_topics is not None:
                stats = st.session_state.import_stats

                st.divider()
                st.write("**Extraction Summary:**")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Files Processed", stats["files_processed"])
                col2.metric("Pages Scanned", stats["total_pages"])
                col3.metric("Topics Found", stats.get("final_topics", stats.get("final_candidates", 0)))
                col4.metric("Adaptive Cap", stats.get("adaptive_cap", "N/A"))

                # Detailed extraction pipeline stats
                with st.expander("Extraction Pipeline Details"):
                    st.caption("How topics were filtered at each stage:")
                    st.write(f"1. **Raw candidates extracted:** {stats.get('raw_candidates', stats.get('initial_candidates', 0))}")
                    st.write(f"2. **After header filter (>10% of pages removed):** {stats.get('after_header_filter', 'N/A')}")
                    st.write(f"3. **After frequency filter (min 2 or 3% pages):** {stats.get('after_frequency_filter', 'N/A')}")
                    st.write(f"4. **After similarity clustering (90% threshold):** {stats.get('after_clustering', 'N/A')}")
                    st.write(f"5. **After hierarchical merge:** {stats.get('after_hierarchical_merge', 'N/A')}")
                    st.write(f"6. **Final topics (ranked & capped):** {stats.get('final_topics', stats.get('final_candidates', 0))}")

                    reduction_pct = 0
                    initial = stats.get('raw_candidates', stats.get('initial_candidates', 0))
                    final = stats.get('final_topics', stats.get('final_candidates', 0))
                    if initial > 0:
                        reduction_pct = round((1 - final / initial) * 100, 1)
                    st.success(f"Reduced by {reduction_pct}% ({initial} → {final} topics)")

                # Show subtopics if available
                if stats.get("subtopics") and len(stats["subtopics"]) > 0:
                    show_subtopics = st.checkbox(
                        f"Show {len(stats['subtopics'])} subtopic(s) that were merged into parent topics",
                        value=False
                    )
                    if show_subtopics:
                        st.caption("These topics were merged hierarchically (e.g., 'Topic I: Part A' → 'Topic')")
                        subtopics_df = pd.DataFrame(stats["subtopics"])
                        st.dataframe(
                            subtopics_df[["topic_name", "parent_topic"]],
                            use_container_width=True,
                            hide_index=True
                        )

                st.divider()
                st.write("**Step 2: Review & Edit Topics**")
                st.caption("Check topics to include, edit names as needed.")

                # Convert to DataFrame for editing
                if st.session_state.imported_topics:
                    import_df = pd.DataFrame(st.session_state.imported_topics)
                    import_df["include"] = True

                    # Handle both old (confidence) and new (occurrence_count) format
                    if "occurrence_count" in import_df.columns:
                        import_df["frequency"] = import_df["occurrence_count"]
                    elif "confidence" in import_df.columns:
                        import_df["frequency"] = import_df["confidence"].round(2)
                    else:
                        import_df["frequency"] = 1

                    # Get existing topics to check for duplicates
                    existing_topics_imp = read_sql(
                        "SELECT topic_name FROM topics WHERE user_id=? AND course_id=?",
                        (user_id, course_id)
                    )
                    existing_normalized = set(normalize_text(t) for t in existing_topics_imp["topic_name"].tolist()) if not existing_topics_imp.empty else set()

                    # Mark duplicates
                    import_df["is_duplicate"] = import_df["topic_name"].apply(
                        lambda x: normalize_text(x) in existing_normalized
                    )
                    import_df.loc[import_df["is_duplicate"], "include"] = False

                    # Select columns for display
                    display_cols = ["include", "topic_name", "source_file", "frequency", "is_duplicate"]
                    if "has_subtopics" in import_df.columns:
                        import_df["subtopics"] = import_df.apply(
                            lambda row: f"✓ ({row['num_subtopics']})" if row.get("has_subtopics") else "",
                            axis=1
                        )
                        display_cols.insert(4, "subtopics")

                    edited_imports = st.data_editor(
                        import_df[display_cols],
                        column_config={
                            "include": st.column_config.CheckboxColumn("Include", default=True),
                            "topic_name": st.column_config.TextColumn("Topic Name"),
                            "source_file": st.column_config.TextColumn("Source File", disabled=True),
                            "frequency": st.column_config.NumberColumn("Frequency", help="Number of times this topic appears", disabled=True),
                            "subtopics": st.column_config.TextColumn("Has Subtopics?", disabled=True),
                            "is_duplicate": st.column_config.CheckboxColumn("Already Exists?", disabled=True)
                        },
                        use_container_width=True,
                        hide_index=True,
                        key="import_topics_editor"
                    )

                    # Count selections
                    selected_count = edited_imports["include"].sum()
                    duplicate_count = edited_imports["is_duplicate"].sum()

                    if duplicate_count > 0:
                        st.warning(f"{duplicate_count} topic(s) already exist in this course and are unchecked.")

                    st.write(f"**Selected: {selected_count} topic(s)**")

                    st.divider()
                    st.write("**Step 3: Create Topics**")

                    if st.button(f"Create {selected_count} Topics", type="primary", disabled=selected_count == 0):
                        created = 0
                        skipped = 0

                        # Get existing normalized topics again for final check
                        existing_topics_imp = read_sql(
                            "SELECT topic_name FROM topics WHERE user_id=? AND course_id=?",
                            (user_id, course_id)
                        )
                        existing_normalized = set(normalize_text(t) for t in existing_topics_imp["topic_name"].tolist()) if not existing_topics_imp.empty else set()

                        for _, row in edited_imports.iterrows():
                            if not row["include"]:
                                continue

                            topic_name_imp = row["topic_name"].strip()
                            normalized = normalize_text(topic_name_imp)

                            # Skip if already exists
                            if normalized in existing_normalized:
                                skipped += 1
                                continue

                            # Insert topic
                            execute_returning(
                                "INSERT INTO topics(user_id, course_id, topic_name, weight_points, notes) VALUES(?,?,?,?,?)",
                                (user_id, course_id, topic_name_imp, 0, f"Imported from: {row['source_file']}")
                            )
                            existing_normalized.add(normalized)
                            created += 1

                        # Clear session state
                        st.session_state.imported_topics = None
                        st.session_state.import_stats = None

                        if created > 0:
                            st.success(f"Created {created} new topic(s)!")
                        if skipped > 0:
                            st.info(f"Skipped {skipped} duplicate(s).")

                        st.info("Expand Topics above to set weight points for your new topics.")
                        st.rerun()
                else:
                    st.info("No topics were extracted. Try uploading different PDF files.")

                # Clear button
                if st.button("Clear & Start Over"):
                    st.session_state.imported_topics = None
                    st.session_state.import_stats = None
                    st.rerun()

# ============ STUDY TAB ============
# Contains: Study Sessions, Exercises, Timed Attempts, Lecture Calendar, Export
with tabs[2]:
    st.header("Study & Practice")
    st.caption("Log study sessions, exercises, timed attempts, and manage lectures.")

    # ============ STUDY SESSIONS EXPANDER ============
    with st.expander("Study Sessions", expanded=True):
        st.caption("Log when you review/study a topic. Quality: 1=distracted, 3=normal, 5=deep focus")

        topics_df_study = read_sql("SELECT id, topic_name FROM topics WHERE user_id=? AND course_id=? ORDER BY topic_name",
                             (user_id, course_id))

        if topics_df_study.empty:
            st.warning("Add topics first!")
        else:
            with st.form("study_form"):
                topic_options_study = topics_df_study["topic_name"].tolist()
                selected_topic_study = st.selectbox("Topic studied", topic_options_study)
                topic_id_study = int(topics_df_study.loc[topics_df_study["topic_name"] == selected_topic_study, "id"].iloc[0])

                col1, col2, col3 = st.columns(3)
                with col1:
                    study_date = st.date_input("Date", value=date.today(), key="study_date")
                with col2:
                    duration = st.number_input("Duration (mins)", min_value=5, value=30, step=5)
                with col3:
                    quality = st.slider("Quality (1-5)", min_value=1, max_value=5, value=3)

                notes_study = st.text_area("Notes (optional)", key="study_notes")

                if st.form_submit_button("Save Study Session"):
                    execute_returning("INSERT INTO study_sessions(topic_id, session_date, duration_mins, quality, notes) VALUES(?,?,?,?,?)",
                                     (topic_id_study, str(study_date), duration, quality, notes_study))
                    st.success("Study session logged!")
                    st.rerun()

            st.write("**Recent Study Sessions:**")
            sessions_df = read_sql("""
                SELECT s.id, t.topic_name, s.session_date, s.duration_mins, s.quality, s.notes
                FROM study_sessions s
                JOIN topics t ON s.topic_id = t.id
                WHERE t.user_id = ? AND t.course_id = ?
                ORDER BY s.session_date DESC
                LIMIT 30
            """, (user_id, course_id))

            if not sessions_df.empty:
                sessions_df["delete"] = False
                edited_sessions = st.data_editor(
                    sessions_df,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "delete": st.column_config.CheckboxColumn("Delete", default=False),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="sessions_editor"
                )

                if st.button("Delete Selected Sessions"):
                    to_delete = edited_sessions[edited_sessions["delete"] == True]["id"].tolist()
                    if to_delete:
                        for sid in to_delete:
                            execute("DELETE FROM study_sessions WHERE id=?", (int(sid),))
                        st.success(f"Deleted {len(to_delete)} session(s)!")
                        st.rerun()

    # ============ EXERCISES EXPANDER ============
    with st.expander("Exercises", expanded=False):
        st.caption("Log practice questions/exercises completed for a topic.")

        topics_df_ex = read_sql("SELECT id, topic_name FROM topics WHERE user_id=? AND course_id=? ORDER BY topic_name",
                             (user_id, course_id))

        if topics_df_ex.empty:
            st.warning("Add topics first!")
        else:
            with st.form("exercise_form"):
                topic_options_ex = topics_df_ex["topic_name"].tolist()
                selected_topic_ex = st.selectbox("Topic", topic_options_ex)
                topic_id_ex = int(topics_df_ex.loc[topics_df_ex["topic_name"] == selected_topic_ex, "id"].iloc[0])

                col1, col2, col3 = st.columns(3)
                with col1:
                    ex_date = st.date_input("Date", value=date.today(), key="ex_date")
                with col2:
                    total_q = st.number_input("Total questions", min_value=1, value=10)
                with col3:
                    correct = st.number_input("Correct answers", min_value=0, max_value=100, value=10)

                source_ex = st.text_input("Source (optional)", placeholder="e.g., 2023 Past Paper", key="ex_source")
                notes_ex = st.text_area("Notes (optional)", key="ex_notes")

                if st.form_submit_button("Save Exercises"):
                    execute_returning("INSERT INTO exercises(topic_id, exercise_date, total_questions, correct_answers, source, notes) VALUES(?,?,?,?,?,?)",
                                     (topic_id_ex, str(ex_date), total_q, min(correct, total_q), source_ex, notes_ex))
                    st.success(f"Logged {min(correct, total_q)}/{total_q} correct!")
                    st.rerun()

            st.write("**Recent Exercises:**")
            exercises_df = read_sql("""
                SELECT e.id, t.topic_name, e.exercise_date, e.total_questions, e.correct_answers, e.source
                FROM exercises e
                JOIN topics t ON e.topic_id = t.id
                WHERE t.user_id = ? AND t.course_id = ?
                ORDER BY e.exercise_date DESC
                LIMIT 30
            """, (user_id, course_id))

            if not exercises_df.empty:
                exercises_df["score"] = (exercises_df["correct_answers"] / exercises_df["total_questions"] * 100).round(0).astype(int).astype(str) + "%"
                exercises_df["delete"] = False

                edited_exercises = st.data_editor(
                    exercises_df,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "delete": st.column_config.CheckboxColumn("Delete", default=False),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="exercises_editor"
                )

                if st.button("Delete Selected Exercises"):
                    to_delete = edited_exercises[edited_exercises["delete"] == True]["id"].tolist()
                    if to_delete:
                        for eid in to_delete:
                            execute("DELETE FROM exercises WHERE id=?", (int(eid),))
                        st.success(f"Deleted {len(to_delete)} exercise(s)!")
                        st.rerun()

    # ============ TIMED ATTEMPTS EXPANDER ============
    with st.expander("Timed Attempts", expanded=False):
        st.caption("Log timed past-paper or practice exam attempts. Performance on specific topics boosts your readiness predictions.")

        # Get topics for multi-select
        topics_df_ta = read_sql("SELECT topic_name FROM topics WHERE user_id=? AND course_id=? ORDER BY topic_name",
                                (user_id, course_id))
        topic_names_ta = topics_df_ta["topic_name"].tolist() if not topics_df_ta.empty else []

        st.write("**Log New Attempt:**")
        with st.form("timed_attempt_form"):
            col1, col2 = st.columns(2)
            with col1:
                ta_date = st.date_input("Attempt date", value=date.today(), key="ta_date")
                ta_source = st.text_input("Source", placeholder="e.g., 2023 Past Paper, Mock Exam 1")
            with col2:
                ta_minutes = st.number_input("Duration (minutes)", min_value=1, value=60)
                ta_score = st.slider("Score (%)", min_value=0, max_value=100, value=70, help="Your percentage score on this attempt")

            if topic_names_ta:
                ta_topics = st.multiselect("Topics covered in this attempt", topic_names_ta,
                                           help="Select all topics that were tested in this paper/exam")
            else:
                ta_topics = []
                st.warning("Add topics first to tag them in your attempts.")

            ta_notes = st.text_area("Notes (optional)", placeholder="e.g., Struggled with Q3, ran out of time on last section", key="ta_notes")

            if st.form_submit_button("Log Attempt", type="primary"):
                if ta_source.strip():
                    topics_str = ", ".join(ta_topics) if ta_topics else ""
                    execute_returning(
                        "INSERT INTO timed_attempts(user_id, course_id, attempt_date, source, minutes, score_pct, topics, notes) VALUES(?,?,?,?,?,?,?,?)",
                        (user_id, course_id, str(ta_date), ta_source.strip(), ta_minutes, ta_score / 100.0, topics_str, ta_notes)
                    )
                    st.success("Attempt logged! Your readiness predictions have been updated.")
                    st.rerun()
                else:
                    st.error("Please enter a source for this attempt.")

        st.divider()

        # Display existing timed attempts
        timed_df = read_sql("""
            SELECT id, attempt_date, source, minutes, score_pct, topics, notes
            FROM timed_attempts
            WHERE user_id=? AND course_id=?
            ORDER BY attempt_date DESC
        """, (user_id, course_id))

        if not timed_df.empty:
            st.write(f"**Your Timed Attempts ({len(timed_df)} total):**")

            # Convert date column to datetime for data_editor compatibility
            timed_df["attempt_date"] = pd.to_datetime(timed_df["attempt_date"], errors="coerce")

            # Add delete column
            timed_df["delete"] = False
            timed_df["score_pct"] = (timed_df["score_pct"] * 100).round(0).astype(int)

            edited_timed = st.data_editor(
                timed_df[["id", "attempt_date", "source", "minutes", "score_pct", "topics", "notes", "delete"]],
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "attempt_date": st.column_config.DateColumn("Date"),
                    "source": st.column_config.TextColumn("Source"),
                    "minutes": st.column_config.NumberColumn("Mins", min_value=1),
                    "score_pct": st.column_config.ProgressColumn("Score %", format="%d%%", min_value=0, max_value=100),
                    "topics": st.column_config.TextColumn("Topics Covered"),
                    "notes": st.column_config.TextColumn("Notes"),
                    "delete": st.column_config.CheckboxColumn("Delete?")
                },
                use_container_width=True,
                hide_index=True,
                key="timed_attempts_editor"
            )

            if st.button("Delete Selected Attempts"):
                to_delete = edited_timed[edited_timed["delete"] == True]["id"].tolist()
                if to_delete:
                    for tid in to_delete:
                        execute("DELETE FROM timed_attempts WHERE id=? AND user_id=?", (int(tid), user_id))
                    st.success(f"Deleted {len(to_delete)} attempt(s)!")
                    st.rerun()

            # Stats summary
            st.divider()
            st.write("**Performance Summary:**")
            col1, col2, col3 = st.columns(3)
            with col1:
                avg_score = timed_df["score_pct"].mean()
                st.metric("Average Score", f"{avg_score:.0f}%")
            with col2:
                total_mins = timed_df["minutes"].sum()
                st.metric("Total Practice Time", f"{total_mins // 60}h {total_mins % 60}m")
            with col3:
                recent_count = len(timed_df[pd.to_datetime(timed_df["attempt_date"]).dt.date >= (date.today() - timedelta(days=14))])
                st.metric("Last 14 Days", f"{recent_count} attempts")
        else:
            st.info("No timed attempts logged yet. Log your first practice exam above!")

    # ============ LECTURE CALENDAR EXPANDER ============
    with st.expander("Lecture Calendar", expanded=False):
        st.caption("Schedule lectures and track attendance. Topics in lectures boost mastery when attended.")

        topics_df_lec = read_sql("SELECT topic_name FROM topics WHERE user_id=? AND course_id=? ORDER BY topic_name",
                             (user_id, course_id))
        topic_names_lec = topics_df_lec["topic_name"].tolist() if not topics_df_lec.empty else []

        st.write("**Schedule New Lecture:**")
        with st.form("lecture_form"):
            col1, col2 = st.columns(2)
            with col1:
                l_date = st.date_input("Lecture date", value=date.today(), key="lec_date")
            with col2:
                l_time = st.text_input("Time (optional)", placeholder="e.g., 10:00 AM")

            topics_planned = st.text_input("Topics to be covered (comma separated)",
                                           placeholder=", ".join(topic_names_lec[:3]) if topic_names_lec else "e.g., Topic A, Topic B")
            notes_lec = st.text_area("Notes (optional)", key="lec_notes")

            if st.form_submit_button("Schedule Lecture"):
                execute_returning("INSERT INTO scheduled_lectures(user_id, course_id, lecture_date, lecture_time, topics_planned, notes) VALUES(?,?,?,?,?,?)",
                                 (user_id, course_id, str(l_date), l_time, topics_planned, notes_lec))
                st.success("Lecture scheduled!")
                st.rerun()

        lectures_df = read_sql("""
            SELECT * FROM scheduled_lectures
            WHERE user_id=? AND course_id=?
            ORDER BY lecture_date
        """, (user_id, course_id))

        if not lectures_df.empty:
            today_lec = date.today()

            lectures_df["lecture_date_parsed"] = pd.to_datetime(lectures_df["lecture_date"])
            upcoming = lectures_df[lectures_df["lecture_date_parsed"].dt.date >= today_lec].copy()
            past = lectures_df[lectures_df["lecture_date_parsed"].dt.date < today_lec].copy()

            st.write("**Upcoming Lectures:**")
            if not upcoming.empty:
                upcoming["attended"] = upcoming["attended"].fillna(0).astype(int)
                upcoming_display = upcoming[["id", "lecture_date", "lecture_time", "topics_planned", "notes"]].copy()
                upcoming_display["lecture_date"] = pd.to_datetime(upcoming_display["lecture_date"])

                edited_upcoming = st.data_editor(
                    upcoming_display,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "lecture_date": st.column_config.DateColumn("Date", format="ddd DD/MM"),
                        "lecture_time": st.column_config.TextColumn("Time"),
                        "topics_planned": st.column_config.TextColumn("Topics"),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="upcoming_lectures"
                )

                if st.button("Save Upcoming Lecture Changes"):
                    for _, r in edited_upcoming.iterrows():
                        execute("UPDATE scheduled_lectures SET lecture_date=?, lecture_time=?, topics_planned=?, notes=? WHERE id=? AND user_id=?",
                               (pd.to_datetime(r["lecture_date"]).strftime("%Y-%m-%d"), r["lecture_time"], r["topics_planned"], r.get("notes"), int(r["id"]), user_id))
                    st.success("Updated!")
                    st.rerun()
            else:
                st.info("No upcoming lectures scheduled.")

            st.write("**Past Lectures (mark attendance):**")
            if not past.empty:
                past["attended"] = past["attended"].apply(lambda x: True if x == 1 else False)
                past_display = past[["id", "lecture_date", "lecture_time", "topics_planned", "attended"]].copy()
                past_display["lecture_date"] = pd.to_datetime(past_display["lecture_date"])

                edited_past = st.data_editor(
                    past_display,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "lecture_date": st.column_config.DateColumn("Date", format="ddd DD/MM", disabled=True),
                        "lecture_time": st.column_config.TextColumn("Time", disabled=True),
                        "topics_planned": st.column_config.TextColumn("Topics", disabled=True),
                        "attended": st.column_config.CheckboxColumn("Attended"),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="past_lectures"
                )

                if st.button("Save Attendance"):
                    for _, r in edited_past.iterrows():
                        execute("UPDATE scheduled_lectures SET attended=? WHERE id=? AND user_id=?",
                               (1 if r["attended"] else 0, int(r["id"]), user_id))
                    st.success("Attendance saved! Mastery updated.")
                    st.rerun()
            else:
                st.info("No past lectures.")

            st.write("**Delete Lectures:**")
            lec_options = lectures_df.apply(lambda r: f"{r['lecture_date']} - {r['topics_planned'][:30] if r['topics_planned'] else 'No topics'}", axis=1).tolist()
            lec_to_delete = st.selectbox("Select lecture to delete", lec_options, key="del_lec")
            if st.button("Delete Selected Lecture"):
                lec_idx = lec_options.index(lec_to_delete)
                lec_id = int(lectures_df.iloc[lec_idx]["id"])
                execute("DELETE FROM scheduled_lectures WHERE id=? AND user_id=?", (lec_id, user_id))
                st.success("Lecture deleted!")
                st.rerun()
        else:
            st.info("No lectures scheduled yet. Add one above!")

    # ============ EXPORT DATA EXPANDER ============
    with st.expander("Export Data", expanded=False):
        topics_export = read_sql("SELECT * FROM topics WHERE user_id=? AND course_id=?", (user_id, course_id))
        sessions_export = read_sql("""
            SELECT s.*, t.topic_name FROM study_sessions s
            JOIN topics t ON s.topic_id = t.id
            WHERE t.user_id = ? AND t.course_id = ?
        """, (user_id, course_id))
        exercises_export = read_sql("""
            SELECT e.*, t.topic_name FROM exercises e
            JOIN topics t ON e.topic_id = t.id
            WHERE t.user_id = ? AND t.course_id = ?
        """, (user_id, course_id))
        lectures_export = read_sql("SELECT * FROM scheduled_lectures WHERE user_id=? AND course_id=?", (user_id, course_id))
        exams_export = read_sql("SELECT * FROM exams WHERE user_id=? AND course_id=?", (user_id, course_id))
        timed_export = read_sql("SELECT * FROM timed_attempts WHERE user_id=? AND course_id=?", (user_id, course_id))
        assessments_export = read_sql("SELECT * FROM assessments WHERE user_id=? AND course_id=?", (user_id, course_id))

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("Topics", topics_export.to_csv(index=False).encode("utf-8"), "topics.csv", "text/csv", key="exp_topics")
            st.download_button("Study Sessions", sessions_export.to_csv(index=False).encode("utf-8"), "study_sessions.csv", "text/csv", key="exp_sessions")
            st.download_button("Exercises", exercises_export.to_csv(index=False).encode("utf-8"), "exercises.csv", "text/csv", key="exp_exercises")
            st.download_button("Assessments", assessments_export.to_csv(index=False).encode("utf-8"), "assessments.csv", "text/csv", key="exp_assessments")
        with col2:
            st.download_button("Lectures", lectures_export.to_csv(index=False).encode("utf-8"), "lectures.csv", "text/csv", key="exp_lectures")
            st.download_button("Exams", exams_export.to_csv(index=False).encode("utf-8"), "exams.csv", "text/csv", key="exp_exams")
            st.download_button("Timed Attempts", timed_export.to_csv(index=False).encode("utf-8"), "timed_attempts.csv", "text/csv", key="exp_timed")
