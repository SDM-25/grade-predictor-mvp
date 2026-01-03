"""
Study recommendations generator.
Pure Python business logic - NO Streamlit dependencies.
"""

from datetime import date
import pandas as pd


def generate_recommendations(
    topics_scored: pd.DataFrame,
    upcoming_lectures: pd.DataFrame,
    days_left: int,
    today: date,
    is_retake: bool = False
) -> list:
    """
    Generate smart study recommendations based on gaps, lectures, and exam proximity.

    Args:
        topics_scored: DataFrame with columns: topic_name, mastery, readiness, gap_score, weight_points, last_activity
        upcoming_lectures: DataFrame with columns: lecture_date, topics_planned
        days_left: Days until exam
        today: Current date
        is_retake: Whether this is a retake (no lectures)

    Returns:
        List of recommendation strings (max 8)
    """
    recommendations = []

    if topics_scored.empty:
        return ["Add topics to get personalized recommendations."]

    gaps = topics_scored.sort_values("gap_score", ascending=False)

    # Lecture-based recommendations (skip for retakes)
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
                                recommendations.append(f"URGENT: Review **{topic}** before lecture on {lec_date.strftime('%a %d/%m')}")
                            elif mastery < 4:
                                recommendations.append(f"Prep: Brush up on **{topic}** before lecture on {lec_date.strftime('%a %d/%m')}")

    # Time-based recommendations
    if days_left <= 7:
        priority = "EXAM WEEK"
        top_gaps = gaps.head(3)
        for _, g in top_gaps.iterrows():
            if g["readiness"] < 0.6:
                recommendations.append(f"{priority}: Focus on **{g['topic_name']}** (weight: {g['weight_points']}, readiness: {g['readiness']*100:.0f}%)")
    elif days_left <= 14:
        top_gaps = gaps.head(4)
        for _, g in top_gaps.iterrows():
            if g["readiness"] < 0.7:
                recommendations.append(f"**2 weeks left**: Prioritize **{g['topic_name']}** (gap score: {g['gap_score']:.1f})")
    elif days_left <= 30:
        top_gaps = gaps.head(5)
        for _, g in top_gaps.iterrows():
            if g["mastery"] < 3:
                recommendations.append(f"Study **{g['topic_name']}** - mastery only {g['mastery']:.1f}/5")

    # Stale topics (mastery decaying)
    stale_topics = topics_scored[
        (topics_scored["mastery"] >= 2) &
        (topics_scored["readiness"] < topics_scored["mastery"] / 5.0 * 0.7)
    ].head(3)
    for _, t in stale_topics.iterrows():
        recommendations.append(f"**Refresh**: {t['topic_name']} - mastery decaying (last activity: {t['last_activity'] or 'never'})")

    # Untouched high-weight topics
    untouched = topics_scored[topics_scored["mastery"] == 0].sort_values("weight_points", ascending=False).head(2)
    for _, t in untouched.iterrows():
        if t["weight_points"] > 0:
            recommendations.append(f"**Start**: {t['topic_name']} (worth {t['weight_points']} points, not yet studied)")

    # Fallback if no recommendations
    if not recommendations:
        avg_readiness = topics_scored["readiness"].mean()
        if avg_readiness >= 0.8:
            recommendations.append("**Great progress!** Focus on practice exams and timed exercises.")
        elif avg_readiness >= 0.6:
            recommendations.append("**Good progress!** Keep up the consistent study sessions.")
        else:
            recommendations.append("**More work needed.** Prioritize high-weight topics first.")

    return recommendations[:8]
