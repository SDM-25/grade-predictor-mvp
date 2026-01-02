import sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

DB_PATH = "grade_predictor.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT NOT NULL UNIQUE,
        total_marks INTEGER NOT NULL DEFAULT 120,
        target_marks INTEGER NOT NULL DEFAULT 90
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        exam_name TEXT NOT NULL,
        exam_date DATE NOT NULL,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        topic_name TEXT NOT NULL,
        weight_points REAL NOT NULL DEFAULT 0,
        notes TEXT,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS study_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL,
        session_date DATE NOT NULL,
        duration_mins INTEGER NOT NULL DEFAULT 30,
        quality INTEGER NOT NULL DEFAULT 3,
        notes TEXT,
        FOREIGN KEY (topic_id) REFERENCES topics(id)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL,
        exercise_date DATE NOT NULL,
        total_questions INTEGER NOT NULL,
        correct_answers INTEGER NOT NULL,
        source TEXT,
        notes TEXT,
        FOREIGN KEY (topic_id) REFERENCES topics(id)
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_lectures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        lecture_date DATE NOT NULL,
        lecture_time TEXT,
        topics_planned TEXT,
        attended INTEGER DEFAULT NULL,
        notes TEXT,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );
    """)
    
    conn.commit()
    conn.close()

def get_or_create_course(course_name: str) -> int:
    conn = get_conn()
    row = conn.execute("SELECT id FROM courses WHERE course_name=?", (course_name,)).fetchone()
    if row:
        course_id = row[0]
    else:
        cur = conn.execute("INSERT INTO courses(course_name) VALUES(?)", (course_name,))
        course_id = cur.lastrowid
        conn.commit()
    conn.close()
    return course_id

def compute_mastery(topic_id: int, today: date) -> tuple:
    """
    Compute mastery (0-5) based on:
    - Exercises: 50% weight (success rate * recency)
    - Study sessions: 35% weight (count * quality * recency)
    - Lectures: 15% weight (attendance on topic)
    """
    conn = get_conn()
    
    exercises = conn.execute("""
        SELECT exercise_date, total_questions, correct_answers 
        FROM exercises WHERE topic_id=? ORDER BY exercise_date DESC
    """, (topic_id,)).fetchall()
    
    exercise_score = 0.0
    exercise_count = len(exercises)
    if exercises:
        total_q = sum(e[1] for e in exercises)
        total_correct = sum(e[2] for e in exercises)
        if total_q > 0:
            success_rate = total_correct / total_q
            recent_exercises = [e for e in exercises if (today - pd.to_datetime(e[0]).date()).days <= 14]
            recency_bonus = min(len(recent_exercises) * 0.2, 1.0)
            exercise_score = success_rate * (0.7 + 0.3 * recency_bonus)
    
    sessions = conn.execute("""
        SELECT session_date, duration_mins, quality 
        FROM study_sessions WHERE topic_id=? ORDER BY session_date DESC
    """, (topic_id,)).fetchall()
    
    study_score = 0.0
    study_count = len(sessions)
    if sessions:
        weighted_sessions = 0.0
        for s in sessions:
            days_ago = (today - pd.to_datetime(s[0]).date()).days
            quality = s[2] / 5.0
            duration_factor = min(s[1] / 60.0, 1.5)
            decay = 1.0 if days_ago <= 7 else (0.8 if days_ago <= 14 else (0.6 if days_ago <= 30 else 0.4))
            weighted_sessions += quality * duration_factor * decay
        study_score = min(weighted_sessions / 3.0, 1.0)
    
    topic_row = conn.execute("SELECT course_id, topic_name FROM topics WHERE id=?", (topic_id,)).fetchone()
    lecture_score = 0.0
    lecture_count = 0
    if topic_row:
        course_id, topic_name = topic_row
        lectures = conn.execute("""
            SELECT lecture_date, attended, topics_planned 
            FROM scheduled_lectures WHERE course_id=? AND attended=1
        """, (course_id,)).fetchall()
        
        for lec in lectures:
            topics_covered = lec[2] or ""
            if topic_name.lower() in topics_covered.lower():
                lecture_count += 1
        lecture_score = min(lecture_count * 0.4, 1.0)
    
    conn.close()
    
    mastery = (exercise_score * 2.5) + (study_score * 1.75) + (lecture_score * 0.75)
    mastery = min(mastery, 5.0)
    
    all_dates = []
    for e in exercises:
        all_dates.append(pd.to_datetime(e[0]).date())
    for s in sessions:
        all_dates.append(pd.to_datetime(s[0]).date())
    last_activity = max(all_dates) if all_dates else None
    
    return mastery, last_activity, exercise_count, study_count, lecture_count

def decay_factor(days_since: int) -> float:
    if days_since <= 7:
        return 1.0
    if days_since <= 14:
        return 0.85
    if days_since <= 30:
        return 0.70
    return 0.55

def compute_readiness(topics_with_mastery: pd.DataFrame, today: date):
    df = topics_with_mastery.copy()
    
    readiness_vals = []
    for _, r in df.iterrows():
        m = float(r["mastery"]) if pd.notna(r["mastery"]) else 0
        lr = r["last_activity"]
        if pd.isna(lr) or lr is None:
            dec = 0.6 if m > 0 else 0.0
        else:
            if isinstance(lr, str):
                lr_date = pd.to_datetime(lr).date()
            else:
                lr_date = lr
            days_since = (today - lr_date).days
            dec = decay_factor(days_since)
        readiness_vals.append((m / 5.0) * dec)
    
    df["readiness"] = readiness_vals
    df["expected_points"] = df["weight_points"] * df["readiness"]
    
    total_weight = float(df["weight_points"].sum()) if not df.empty else 0.0
    total_expected = float(df["expected_points"].sum()) if not df.empty else 0.0
    
    coverage_pct = (df.loc[df["mastery"] >= 1, "weight_points"].sum() / total_weight) if total_weight > 0 else 0.0
    mastery_pct = (float((df["weight_points"] * (df["mastery"] / 5.0)).sum()) / total_weight) if total_weight > 0 else 0.0
    retention_pct = (float((df["weight_points"] * df["readiness"]).sum()) / total_weight) if total_weight > 0 else 0.0
    
    return df, total_expected, total_weight, coverage_pct, mastery_pct, retention_pct

def generate_recommendations(topics_scored: pd.DataFrame, upcoming_lectures: pd.DataFrame, days_left: int, today: date) -> list:
    """Generate smart study recommendations based on gaps, lectures, and exam proximity."""
    recommendations = []
    
    if topics_scored.empty:
        return ["Add topics to get personalized recommendations."]
    
    # Sort by gap score (what needs most work)
    gaps = topics_scored.sort_values("gap_score", ascending=False)
    
    # 1. Urgent: Topics in upcoming lectures (next 3 days) that aren't mastered
    if not upcoming_lectures.empty:
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
    
    # 2. Exam proximity - high-weight gaps become critical
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
    
    # 3. Topics with no recent activity (retention decay)
    stale_topics = topics_scored[
        (topics_scored["mastery"] >= 2) & 
        (topics_scored["readiness"] < topics_scored["mastery"] / 5.0 * 0.7)
    ].head(3)
    for _, t in stale_topics.iterrows():
        recommendations.append(f"🔄 **Refresh**: {t['topic_name']} - mastery decaying (last activity: {t['last_activity'] or 'never'})")
    
    # 4. Topics never studied
    untouched = topics_scored[topics_scored["mastery"] == 0].sort_values("weight_points", ascending=False).head(2)
    for _, t in untouched.iterrows():
        if t["weight_points"] > 0:
            recommendations.append(f"🆕 **Start**: {t['topic_name']} (worth {t['weight_points']} points, not yet studied)")
    
    # 5. General advice based on overall readiness
    if not recommendations:
        avg_readiness = topics_scored["readiness"].mean()
        if avg_readiness >= 0.8:
            recommendations.append("✅ **Great progress!** Focus on practice exams and timed exercises.")
        elif avg_readiness >= 0.6:
            recommendations.append("📈 **Good progress!** Keep up the consistent study sessions.")
        else:
            recommendations.append("📚 **More work needed.** Prioritize high-weight topics first.")
    
    return recommendations[:8]  # Limit to 8 recommendations

# ============ STREAMLIT APP ============

st.set_page_config(page_title="Exam Readiness Predictor", page_icon="📈", layout="wide")
init_db()

st.title("📈 Exam Readiness Predictor")
st.caption("Auto-calculated mastery from study sessions, exercises, and lectures.")

# ============ SIDEBAR ============
with st.sidebar:
    st.header("📚 Course Setup")
    
    conn = get_conn()
    courses = pd.read_sql_query("SELECT * FROM courses", conn)
    conn.close()
    
    course_options = courses["course_name"].tolist() if not courses.empty else []
    
    new_course = st.text_input("Add new course", placeholder="e.g., Microeconomics")
    if st.button("➕ Add Course") and new_course.strip():
        get_or_create_course(new_course.strip())
        st.rerun()
    
    if course_options:
        selected_course = st.selectbox("Select course", course_options)
        course_id = int(courses.loc[courses["course_name"] == selected_course, "id"].iloc[0])
        
        course_row = courses[courses["course_name"] == selected_course].iloc[0]
        total_marks = st.number_input("Total exam marks", min_value=1, value=int(course_row["total_marks"]))
        target_marks = st.number_input("Target marks", min_value=0, max_value=int(total_marks), value=int(course_row["target_marks"]))
        
        if st.button("💾 Save Course Settings"):
            conn = get_conn()
            conn.execute("UPDATE courses SET total_marks=?, target_marks=? WHERE id=?", (total_marks, target_marks, course_id))
            conn.commit()
            conn.close()
            st.success("Saved!")
    else:
        st.warning("Add a course to get started!")
        st.stop()

# ============ TABS ============
tabs = st.tabs(["📊 Dashboard", "📅 Exams", "📖 Topics", "✏️ Study Sessions", "🏋️ Exercises", "🎓 Lecture Calendar", "📤 Export"])

# ============ DASHBOARD ============
with tabs[0]:
    today = date.today()
    
    conn = get_conn()
    exams_df = pd.read_sql_query("SELECT * FROM exams WHERE course_id=? ORDER BY exam_date", conn, params=(course_id,))
    conn.close()
    
    if exams_df.empty:
        st.warning("⚠️ No exams added yet. Go to the Exams tab to add one.")
        exam_date = None
        days_left = 0
    else:
        exam_options = exams_df.apply(lambda r: f"{r['exam_name']} ({r['exam_date']})", axis=1).tolist()
        selected_exam_idx = st.selectbox("Select exam to track", range(len(exam_options)), format_func=lambda i: exam_options[i])
        exam_row = exams_df.iloc[selected_exam_idx]
        exam_date = pd.to_datetime(exam_row["exam_date"]).date()
        days_left = max((exam_date - today).days, 0)
    
    conn = get_conn()
    topics_df = pd.read_sql_query("SELECT id, topic_name, weight_points, notes FROM topics WHERE course_id=? ORDER BY id", conn, params=(course_id,))
    upcoming_lectures = pd.read_sql_query("""
        SELECT * FROM scheduled_lectures 
        WHERE course_id=? AND lecture_date >= ? 
        ORDER BY lecture_date LIMIT 10
    """, conn, params=(course_id, str(today)))
    conn.close()
    
    if topics_df.empty:
        st.info("📖 No topics added yet. Go to Topics tab to add some.")
    else:
        mastery_data = []
        for _, row in topics_df.iterrows():
            m, last_act, ex_cnt, st_cnt, lec_cnt = compute_mastery(int(row["id"]), today)
            mastery_data.append({
                "id": row["id"],
                "topic_name": row["topic_name"],
                "weight_points": row["weight_points"],
                "mastery": round(m, 2),
                "last_activity": last_act,
                "exercises": ex_cnt,
                "study_sessions": st_cnt,
                "lectures": lec_cnt
            })
        
        topics_with_mastery = pd.DataFrame(mastery_data)
        topics_scored, expected_sum, weight_sum, coverage_pct, mastery_pct, retention_pct = compute_readiness(topics_with_mastery, today)
        
        base_pred = expected_sum
        if weight_sum and abs(weight_sum - float(total_marks)) > 1e-6:
            base_pred *= float(total_marks) / float(weight_sum)
        pred_marks = base_pred
        
        # Metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Predicted marks", f"{pred_marks:.1f} / {total_marks}", delta=f"Target {target_marks}")
        c2.metric("Readiness", f"{retention_pct*100:.0f}%")
        c3.metric("Days left", f"{days_left}" if exam_date else "N/A")
        c4.metric("Coverage", f"{coverage_pct*100:.0f}%")
        
        if pred_marks < target_marks - 10:
            status = "🔴 AT RISK"
        elif pred_marks < target_marks:
            status = "🟡 BORDERLINE"
        else:
            status = "🟢 ON TRACK"
        st.write(f"**Status:** {status}")
        
        # Recommendations
        st.subheader("💡 Recommendations")
        topics_scored["gap_score"] = topics_scored["weight_points"] * (1.0 - topics_scored["readiness"])
        recs = generate_recommendations(topics_scored, upcoming_lectures, days_left, today)
        for rec in recs:
            st.markdown(f"- {rec}")
        
        # Top gaps
        st.subheader("🎯 Top Gaps")
        gaps = topics_scored.sort_values("gap_score", ascending=False).head(6)
        st.dataframe(
            gaps[["topic_name", "weight_points", "mastery", "exercises", "study_sessions", "readiness", "gap_score"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "mastery": st.column_config.ProgressColumn("Mastery", format="%.1f/5", min_value=0, max_value=5),
                "readiness": st.column_config.ProgressColumn("Readiness", format="%.0f%%", min_value=0, max_value=1),
            }
        )
        
        # Upcoming lectures
        if not upcoming_lectures.empty:
            st.subheader("📅 Upcoming Lectures")
            upcoming_lectures["lecture_date"] = pd.to_datetime(upcoming_lectures["lecture_date"])
            st.dataframe(
                upcoming_lectures[["lecture_date", "lecture_time", "topics_planned"]].head(5),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "lecture_date": st.column_config.DateColumn("Date", format="ddd DD/MM"),
                }
            )
        
        # All topics
        st.subheader("📋 All Topics")
        st.dataframe(
            topics_scored[["topic_name", "weight_points", "mastery", "last_activity", "exercises", "study_sessions", "lectures", "readiness"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "mastery": st.column_config.ProgressColumn("Mastery", format="%.1f/5", min_value=0, max_value=5),
                "readiness": st.column_config.ProgressColumn("Readiness", format="%.0f%%", min_value=0, max_value=1),
            }
        )

# ============ EXAMS TAB ============
with tabs[1]:
    st.subheader("📅 Manage Exams")
    
    conn = get_conn()
    exams_df = pd.read_sql_query("SELECT * FROM exams WHERE course_id=? ORDER BY exam_date", conn, params=(course_id,))
    conn.close()
    
    with st.form("add_exam"):
        col1, col2 = st.columns(2)
        with col1:
            exam_name = st.text_input("Exam name", placeholder="e.g., Final Exam")
        with col2:
            exam_date_input = st.date_input("Exam date", value=date(2026, 3, 9))
        
        if st.form_submit_button("➕ Add Exam"):
            if exam_name.strip():
                conn = get_conn()
                conn.execute("INSERT INTO exams(course_id, exam_name, exam_date) VALUES(?,?,?)",
                           (course_id, exam_name.strip(), str(exam_date_input)))
                conn.commit()
                conn.close()
                st.success("Exam added!")
                st.rerun()
    
    if not exams_df.empty:
        st.write("**Existing Exams:**")
        exams_df["exam_date"] = pd.to_datetime(exams_df["exam_date"])
        
        edited_exams = st.data_editor(
            exams_df[["id", "exam_name", "exam_date"]],
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "exam_name": st.column_config.TextColumn("Exam Name"),
                "exam_date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            },
            use_container_width=True,
            hide_index=True,
            key="exams_editor"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save Exam Changes"):
                conn = get_conn()
                for _, r in edited_exams.iterrows():
                    conn.execute("UPDATE exams SET exam_name=?, exam_date=? WHERE id=?",
                               (r["exam_name"], pd.to_datetime(r["exam_date"]).strftime("%Y-%m-%d"), int(r["id"])))
                conn.commit()
                conn.close()
                st.success("Exams updated!")
                st.rerun()
        with col2:
            exam_to_delete = st.selectbox("Delete exam", exams_df["exam_name"].tolist(), key="del_exam")
            if st.button("🗑️ Delete Selected Exam"):
                conn = get_conn()
                conn.execute("DELETE FROM exams WHERE course_id=? AND exam_name=?", (course_id, exam_to_delete))
                conn.commit()
                conn.close()
                st.success("Deleted!")
                st.rerun()

# ============ TOPICS TAB ============
with tabs[2]:
    st.subheader("📖 Manage Topics")
    
    conn = get_conn()
    topics_df = pd.read_sql_query("SELECT id, topic_name, weight_points, notes FROM topics WHERE course_id=? ORDER BY id", conn, params=(course_id,))
    conn.close()
    
    with st.form("add_topic"):
        col1, col2 = st.columns([3, 1])
        with col1:
            topic_name = st.text_input("Topic name", placeholder="e.g., Supply and Demand")
        with col2:
            weight = st.number_input("Weight (points)", min_value=0, value=10)
        
        if st.form_submit_button("➕ Add Topic"):
            if topic_name.strip():
                conn = get_conn()
                conn.execute("INSERT INTO topics(course_id, topic_name, weight_points) VALUES(?,?,?)",
                           (course_id, topic_name.strip(), weight))
                conn.commit()
                conn.close()
                st.success("Topic added!")
                st.rerun()
    
    if not topics_df.empty:
        st.write("**Existing Topics:**")
        edited_topics = st.data_editor(
            topics_df,
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
            if st.button("💾 Save Topic Changes"):
                conn = get_conn()
                for _, r in edited_topics.iterrows():
                    if pd.notna(r["id"]):
                        conn.execute("UPDATE topics SET topic_name=?, weight_points=?, notes=? WHERE id=?",
                                   (r["topic_name"], float(r["weight_points"]), r.get("notes"), int(r["id"])))
                conn.commit()
                conn.close()
                st.success("Topics updated!")
                st.rerun()
        with col2:
            topic_to_delete = st.selectbox("Delete topic", topics_df["topic_name"].tolist(), key="del_topic")
            if st.button("🗑️ Delete Selected Topic"):
                conn = get_conn()
                topic_id_del = topics_df.loc[topics_df["topic_name"] == topic_to_delete, "id"].iloc[0]
                conn.execute("DELETE FROM study_sessions WHERE topic_id=?", (int(topic_id_del),))
                conn.execute("DELETE FROM exercises WHERE topic_id=?", (int(topic_id_del),))
                conn.execute("DELETE FROM topics WHERE id=?", (int(topic_id_del),))
                conn.commit()
                conn.close()
                st.success("Topic and related data deleted!")
                st.rerun()

# ============ STUDY SESSIONS TAB ============
with tabs[3]:
    st.subheader("✏️ Study Sessions")
    st.caption("Log when you review/study a topic. Quality: 1=distracted, 3=normal, 5=deep focus")
    
    conn = get_conn()
    topics_df = pd.read_sql_query("SELECT id, topic_name FROM topics WHERE course_id=? ORDER BY topic_name", conn, params=(course_id,))
    conn.close()
    
    if topics_df.empty:
        st.warning("Add topics first!")
    else:
        with st.form("study_form"):
            topic_options = topics_df["topic_name"].tolist()
            selected_topic = st.selectbox("Topic studied", topic_options)
            topic_id = int(topics_df.loc[topics_df["topic_name"] == selected_topic, "id"].iloc[0])
            
            col1, col2, col3 = st.columns(3)
            with col1:
                study_date = st.date_input("Date", value=date.today())
            with col2:
                duration = st.number_input("Duration (mins)", min_value=5, value=30, step=5)
            with col3:
                quality = st.slider("Quality (1-5)", min_value=1, max_value=5, value=3)
            
            notes = st.text_area("Notes (optional)")
            
            if st.form_submit_button("📝 Save Study Session"):
                conn = get_conn()
                conn.execute("INSERT INTO study_sessions(topic_id, session_date, duration_mins, quality, notes) VALUES(?,?,?,?,?)",
                           (topic_id, str(study_date), duration, quality, notes))
                conn.commit()
                conn.close()
                st.success("Study session logged!")
                st.rerun()
        
        st.subheader("Recent Study Sessions")
        conn = get_conn()
        sessions_df = pd.read_sql_query("""
            SELECT s.id, t.topic_name, s.session_date, s.duration_mins, s.quality, s.notes
            FROM study_sessions s
            JOIN topics t ON s.topic_id = t.id
            WHERE t.course_id = ?
            ORDER BY s.session_date DESC
            LIMIT 30
        """, conn, params=(course_id,))
        conn.close()
        
        if not sessions_df.empty:
            sessions_df["delete"] = False
            edited_sessions = st.data_editor(
                sessions_df,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "delete": st.column_config.CheckboxColumn("🗑️ Delete", default=False),
                },
                use_container_width=True,
                hide_index=True,
                key="sessions_editor"
            )
            
            if st.button("🗑️ Delete Selected Sessions"):
                to_delete = edited_sessions[edited_sessions["delete"] == True]["id"].tolist()
                if to_delete:
                    conn = get_conn()
                    for sid in to_delete:
                        conn.execute("DELETE FROM study_sessions WHERE id=?", (int(sid),))
                    conn.commit()
                    conn.close()
                    st.success(f"Deleted {len(to_delete)} session(s)!")
                    st.rerun()

# ============ EXERCISES TAB ============
with tabs[4]:
    st.subheader("🏋️ Exercises")
    st.caption("Log practice questions/exercises completed for a topic.")
    
    conn = get_conn()
    topics_df = pd.read_sql_query("SELECT id, topic_name FROM topics WHERE course_id=? ORDER BY topic_name", conn, params=(course_id,))
    conn.close()
    
    if topics_df.empty:
        st.warning("Add topics first!")
    else:
        with st.form("exercise_form"):
            topic_options = topics_df["topic_name"].tolist()
            selected_topic = st.selectbox("Topic", topic_options)
            topic_id = int(topics_df.loc[topics_df["topic_name"] == selected_topic, "id"].iloc[0])
            
            col1, col2, col3 = st.columns(3)
            with col1:
                ex_date = st.date_input("Date", value=date.today())
            with col2:
                total_q = st.number_input("Total questions", min_value=1, value=10)
            with col3:
                correct = st.number_input("Correct answers", min_value=0, max_value=100, value=10)
            
            source = st.text_input("Source (optional)", placeholder="e.g., 2023 Past Paper")
            notes = st.text_area("Notes (optional)")
            
            if st.form_submit_button("💪 Save Exercises"):
                conn = get_conn()
                conn.execute("INSERT INTO exercises(topic_id, exercise_date, total_questions, correct_answers, source, notes) VALUES(?,?,?,?,?,?)",
                           (topic_id, str(ex_date), total_q, min(correct, total_q), source, notes))
                conn.commit()
                conn.close()
                st.success(f"Logged {min(correct, total_q)}/{total_q} correct!")
                st.rerun()
        
        st.subheader("Recent Exercises")
        conn = get_conn()
        exercises_df = pd.read_sql_query("""
            SELECT e.id, t.topic_name, e.exercise_date, e.total_questions, e.correct_answers, e.source
            FROM exercises e
            JOIN topics t ON e.topic_id = t.id
            WHERE t.course_id = ?
            ORDER BY e.exercise_date DESC
            LIMIT 30
        """, conn, params=(course_id,))
        conn.close()
        
        if not exercises_df.empty:
            exercises_df["score"] = (exercises_df["correct_answers"] / exercises_df["total_questions"] * 100).round(0).astype(int).astype(str) + "%"
            exercises_df["delete"] = False
            
            edited_exercises = st.data_editor(
                exercises_df,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "delete": st.column_config.CheckboxColumn("🗑️ Delete", default=False),
                },
                use_container_width=True,
                hide_index=True,
                key="exercises_editor"
            )
            
            if st.button("🗑️ Delete Selected Exercises"):
                to_delete = edited_exercises[edited_exercises["delete"] == True]["id"].tolist()
                if to_delete:
                    conn = get_conn()
                    for eid in to_delete:
                        conn.execute("DELETE FROM exercises WHERE id=?", (int(eid),))
                    conn.commit()
                    conn.close()
                    st.success(f"Deleted {len(to_delete)} exercise(s)!")
                    st.rerun()

# ============ LECTURE CALENDAR TAB ============
with tabs[5]:
    st.subheader("🎓 Lecture Calendar")
    st.caption("Schedule lectures and track attendance. Topics in lectures boost mastery when attended.")
    
    conn = get_conn()
    topics_df = pd.read_sql_query("SELECT topic_name FROM topics WHERE course_id=? ORDER BY topic_name", conn, params=(course_id,))
    conn.close()
    topic_names = topics_df["topic_name"].tolist() if not topics_df.empty else []
    
    # Add new lecture
    st.write("**Schedule New Lecture:**")
    with st.form("lecture_form"):
        col1, col2 = st.columns(2)
        with col1:
            l_date = st.date_input("Lecture date", value=date.today())
        with col2:
            l_time = st.text_input("Time (optional)", placeholder="e.g., 10:00 AM")
        
        topics_planned = st.text_input("Topics to be covered (comma separated)", 
                                       placeholder=", ".join(topic_names[:3]) if topic_names else "e.g., Topic A, Topic B")
        notes = st.text_area("Notes (optional)")
        
        if st.form_submit_button("📅 Schedule Lecture"):
            conn = get_conn()
            conn.execute("INSERT INTO scheduled_lectures(course_id, lecture_date, lecture_time, topics_planned, notes) VALUES(?,?,?,?,?)",
                       (course_id, str(l_date), l_time, topics_planned, notes))
            conn.commit()
            conn.close()
            st.success("Lecture scheduled!")
            st.rerun()
    
    # Show calendar view
    conn = get_conn()
    lectures_df = pd.read_sql_query("""
        SELECT * FROM scheduled_lectures 
        WHERE course_id=? 
        ORDER BY lecture_date
    """, conn, params=(course_id,))
    conn.close()
    
    if not lectures_df.empty:
        today = date.today()
        
        # Split into upcoming and past
        lectures_df["lecture_date_parsed"] = pd.to_datetime(lectures_df["lecture_date"])
        upcoming = lectures_df[lectures_df["lecture_date_parsed"].dt.date >= today].copy()
        past = lectures_df[lectures_df["lecture_date_parsed"].dt.date < today].copy()
        
        # Upcoming lectures
        st.write("**📅 Upcoming Lectures:**")
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
            
            if st.button("💾 Save Upcoming Lecture Changes"):
                conn = get_conn()
                for _, r in edited_upcoming.iterrows():
                    conn.execute("UPDATE scheduled_lectures SET lecture_date=?, lecture_time=?, topics_planned=?, notes=? WHERE id=?",
                               (pd.to_datetime(r["lecture_date"]).strftime("%Y-%m-%d"), r["lecture_time"], r["topics_planned"], r.get("notes"), int(r["id"])))
                conn.commit()
                conn.close()
                st.success("Updated!")
                st.rerun()
        else:
            st.info("No upcoming lectures scheduled.")
        
        # Past lectures - mark attendance
        st.write("**📋 Past Lectures (mark attendance):**")
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
                    "attended": st.column_config.CheckboxColumn("✅ Attended"),
                },
                use_container_width=True,
                hide_index=True,
                key="past_lectures"
            )
            
            if st.button("💾 Save Attendance"):
                conn = get_conn()
                for _, r in edited_past.iterrows():
                    conn.execute("UPDATE scheduled_lectures SET attended=? WHERE id=?",
                               (1 if r["attended"] else 0, int(r["id"])))
                conn.commit()
                conn.close()
                st.success("Attendance saved! Mastery updated.")
                st.rerun()
        else:
            st.info("No past lectures.")
        
        # Delete lectures
        st.write("**🗑️ Delete Lectures:**")
        lec_options = lectures_df.apply(lambda r: f"{r['lecture_date']} - {r['topics_planned'][:30] if r['topics_planned'] else 'No topics'}", axis=1).tolist()
        lec_to_delete = st.selectbox("Select lecture to delete", lec_options, key="del_lec")
        if st.button("🗑️ Delete Selected Lecture"):
            lec_idx = lec_options.index(lec_to_delete)
            lec_id = int(lectures_df.iloc[lec_idx]["id"])
            conn = get_conn()
            conn.execute("DELETE FROM scheduled_lectures WHERE id=?", (lec_id,))
            conn.commit()
            conn.close()
            st.success("Lecture deleted!")
            st.rerun()
    else:
        st.info("No lectures scheduled yet. Add one above!")

# ============ EXPORT TAB ============
with tabs[6]:
    st.subheader("📤 Export Data")
    
    conn = get_conn()
    topics_export = pd.read_sql_query("SELECT * FROM topics WHERE course_id=?", conn, params=(course_id,))
    sessions_export = pd.read_sql_query("""
        SELECT s.*, t.topic_name FROM study_sessions s
        JOIN topics t ON s.topic_id = t.id
        WHERE t.course_id = ?
    """, conn, params=(course_id,))
    exercises_export = pd.read_sql_query("""
        SELECT e.*, t.topic_name FROM exercises e
        JOIN topics t ON e.topic_id = t.id
        WHERE t.course_id = ?
    """, conn, params=(course_id,))
    lectures_export = pd.read_sql_query("SELECT * FROM scheduled_lectures WHERE course_id=?", conn, params=(course_id,))
    exams_export = pd.read_sql_query("SELECT * FROM exams WHERE course_id=?", conn, params=(course_id,))
    conn.close()
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 Topics", topics_export.to_csv(index=False).encode("utf-8"), "topics.csv", "text/csv")
        st.download_button("📥 Study Sessions", sessions_export.to_csv(index=False).encode("utf-8"), "study_sessions.csv", "text/csv")
        st.download_button("📥 Exercises", exercises_export.to_csv(index=False).encode("utf-8"), "exercises.csv", "text/csv")
    with col2:
        st.download_button("📥 Lectures", lectures_export.to_csv(index=False).encode("utf-8"), "lectures.csv", "text/csv")
        st.download_button("📥 Exams", exams_export.to_csv(index=False).encode("utf-8"), "exams.csv", "text/csv")
