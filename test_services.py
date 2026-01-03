#!/usr/bin/env python3
"""
Smoke tests for the services layer.
Runs against a temporary SQLite database (no Streamlit required).

Usage:
    python test_services.py

This script:
1. Creates a temporary in-memory SQLite database
2. Tests CRUD operations for courses, assessments, topics
3. Tests study activity logging
4. Tests readiness computation and week plan generation
5. Cleans up and reports results
"""

import sys
import os
import tempfile
import json
from datetime import date, timedelta

# Ensure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Override the database path to use a temp file for testing
import db
TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db.SQLITE_PATH = TEMP_DB.name

# Initialize the database schema
db.init_db()

# Now import services (after DB is set up)
from services import (
    # Course CRUD
    create_course, list_courses, get_course, update_course, delete_course,
    # Assessment CRUD
    create_assessment, list_assessments, update_assessment, delete_assessment,
    # Topic CRUD
    create_topic, list_topics, update_topic, delete_topic,
    # Activity logging
    add_study_session, add_exercise, add_timed_attempt,
    # Analytics
    compute_course_readiness, generate_week_plan, generate_recommended_tasks,
)


def test_passed(name: str):
    print(f"  [PASS] {name}")


def test_failed(name: str, error: str):
    print(f"  [FAIL] {name}: {error}")
    return False


def run_tests():
    """Run all smoke tests."""
    print("\n" + "=" * 60)
    print("SERVICES LAYER SMOKE TESTS")
    print("=" * 60)
    print(f"Using temp database: {db.SQLITE_PATH}")
    print()

    all_passed = True
    test_user_id = 1

    # Create a test user first
    db.execute_returning("INSERT INTO users(email, password_hash) VALUES(?,?)", ("test@example.com", ""))

    # ========================================
    # TEST: Course CRUD
    # ========================================
    print("1. Course CRUD")

    # Create course
    result = create_course(test_user_id, "Test Economics", total_marks=100, target_marks=75)
    if result.get("created") and result.get("course_id"):
        test_passed("create_course")
        course_id = result["course_id"]
    else:
        all_passed = test_failed("create_course", str(result))
        return False

    # List courses
    courses = list_courses(test_user_id)
    if len(courses) == 1 and courses[0]["name"] == "Test Economics":
        test_passed("list_courses")
    else:
        all_passed = test_failed("list_courses", f"Expected 1 course, got {len(courses)}")

    # Get course
    course = get_course(test_user_id, course_id)
    if course and course["total_marks"] == 100:
        test_passed("get_course")
    else:
        all_passed = test_failed("get_course", str(course))

    # Update course
    updated = update_course(test_user_id, course_id, target_marks=80)
    if updated and updated["target_marks"] == 80:
        test_passed("update_course")
    else:
        all_passed = test_failed("update_course", str(updated))

    # ========================================
    # TEST: Assessment CRUD
    # ========================================
    print("\n2. Assessment CRUD")

    # Create assessment
    today = date.today()
    exam_date = (today + timedelta(days=30)).isoformat()
    assessment = create_assessment(
        test_user_id, course_id,
        name="Final Exam",
        assessment_type="Exam",
        marks=100,
        due_date=exam_date,
        is_timed=True
    )
    if assessment.get("id"):
        test_passed("create_assessment")
        assessment_id = assessment["id"]
    else:
        all_passed = test_failed("create_assessment", str(assessment))

    # List assessments
    assessments = list_assessments(test_user_id, course_id)
    if len(assessments) >= 1:
        test_passed("list_assessments")
    else:
        all_passed = test_failed("list_assessments", f"Expected >= 1, got {len(assessments)}")

    # Update assessment
    updated_asmt = update_assessment(test_user_id, assessment_id, marks=120)
    if updated_asmt and updated_asmt["marks"] == 120:
        test_passed("update_assessment")
    else:
        all_passed = test_failed("update_assessment", str(updated_asmt))

    # ========================================
    # TEST: Topic CRUD
    # ========================================
    print("\n3. Topic CRUD")

    # Create topics
    topic1 = create_topic(test_user_id, course_id, "Supply and Demand", weight_points=25)
    topic2 = create_topic(test_user_id, course_id, "Market Equilibrium", weight_points=20)
    topic3 = create_topic(test_user_id, course_id, "Elasticity", weight_points=15)

    if topic1.get("id") and topic2.get("id") and topic3.get("id"):
        test_passed("create_topic (x3)")
        topic_id = topic1["id"]
    else:
        all_passed = test_failed("create_topic", "Failed to create topics")

    # List topics
    topics = list_topics(test_user_id, course_id)
    if len(topics) == 3:
        test_passed("list_topics")
    else:
        all_passed = test_failed("list_topics", f"Expected 3, got {len(topics)}")

    # List topics with mastery
    topics_with_mastery = list_topics(test_user_id, course_id, include_mastery=True)
    if topics_with_mastery and "mastery" in topics_with_mastery[0]:
        test_passed("list_topics (with mastery)")
    else:
        all_passed = test_failed("list_topics (with mastery)", "Missing mastery field")

    # Update topic
    updated_topic = update_topic(test_user_id, topic_id, weight_points=30)
    if updated_topic and updated_topic["weight_points"] == 30:
        test_passed("update_topic")
    else:
        all_passed = test_failed("update_topic", str(updated_topic))

    # ========================================
    # TEST: Activity Logging
    # ========================================
    print("\n4. Activity Logging")

    # Add study session
    yesterday = (today - timedelta(days=1)).isoformat()
    session = add_study_session(topic_id, yesterday, duration_mins=45, quality=4)
    if session.get("id"):
        test_passed("add_study_session")
    else:
        all_passed = test_failed("add_study_session", str(session))

    # Add exercise
    exercise = add_exercise(topic_id, today.isoformat(), total_questions=10, correct_answers=8, source="Past Paper")
    if exercise.get("id") and exercise.get("score_pct") == 80.0:
        test_passed("add_exercise")
    else:
        all_passed = test_failed("add_exercise", str(exercise))

    # Add timed attempt
    timed = add_timed_attempt(
        test_user_id, course_id,
        attempt_date=today.isoformat(),
        source="2023 Mock Exam",
        minutes=90,
        score_pct=72.5,
        topics="Supply and Demand, Elasticity"
    )
    if timed.get("id"):
        test_passed("add_timed_attempt")
    else:
        all_passed = test_failed("add_timed_attempt", str(timed))

    # ========================================
    # TEST: Analytics
    # ========================================
    print("\n5. Analytics & Readiness")

    # Compute course readiness
    readiness = compute_course_readiness(test_user_id, course_id)
    if "predicted_marks" in readiness and "status" in readiness and "topics" in readiness:
        test_passed(f"compute_course_readiness (status={readiness['status']}, predicted={readiness['predicted_marks']})")
    else:
        all_passed = test_failed("compute_course_readiness", str(readiness))

    # Generate recommended tasks
    tasks = generate_recommended_tasks(test_user_id, course_id=course_id, max_tasks=5)
    if isinstance(tasks, list):
        test_passed(f"generate_recommended_tasks (got {len(tasks)} tasks)")
    else:
        all_passed = test_failed("generate_recommended_tasks", str(tasks))

    # Generate week plan
    plan = generate_week_plan(test_user_id, course_id=course_id, hours_per_week=10, session_length_mins=60)
    if "days" in plan and "total_sessions" in plan:
        test_passed(f"generate_week_plan (sessions={plan['total_sessions']}, hours={plan['total_hours']})")
    else:
        all_passed = test_failed("generate_week_plan", str(plan))

    # ========================================
    # TEST: Delete Operations
    # ========================================
    print("\n6. Delete Operations")

    # Delete assessment
    if delete_assessment(test_user_id, assessment_id):
        test_passed("delete_assessment")
    else:
        all_passed = test_failed("delete_assessment", "Failed to delete")

    # Delete topic (should cascade to sessions/exercises)
    if delete_topic(test_user_id, topic_id):
        test_passed("delete_topic (with cascade)")
    else:
        all_passed = test_failed("delete_topic", "Failed to delete")

    # Delete course (should cascade everything)
    delete_result = delete_course(test_user_id, course_id)
    if delete_result.get("deleted"):
        test_passed("delete_course (with cascade)")
    else:
        all_passed = test_failed("delete_course", str(delete_result))

    # Verify course is gone
    remaining = list_courses(test_user_id)
    if len(remaining) == 0:
        test_passed("verify deletion")
    else:
        all_passed = test_failed("verify deletion", f"Expected 0 courses, got {len(remaining)}")

    # ========================================
    # SUMMARY
    # ========================================
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)

    # Cleanup temp database
    try:
        os.unlink(db.SQLITE_PATH)
        print(f"\nCleaned up temp database: {db.SQLITE_PATH}")
    except:
        pass

    return all_passed


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
