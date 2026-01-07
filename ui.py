"""
UI Components and Styling for Exam Readiness Predictor
Modern SaaS-style dashboard components
"""
import streamlit as st

# ============ GLOBAL CSS ============
GLOBAL_CSS = """
<style>
/* Typography */
h1 {
    font-size: 1.8rem !important;
    font-weight: 600 !important;
    margin-bottom: 0.5rem !important;
}
h2 {
    font-size: 1.4rem !important;
    font-weight: 600 !important;
    margin-bottom: 0.5rem !important;
    margin-top: 1.5rem !important;
}
h3 {
    font-size: 1.15rem !important;
    font-weight: 600 !important;
    margin-bottom: 0.5rem !important;
}
p, .stMarkdown {
    font-size: 0.95rem !important;
    line-height: 1.5 !important;
}

/* Card styling */
.saas-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1rem;
}
.saas-card-header {
    font-size: 0.85rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.6);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.75rem;
}

/* KPI Card styling */
.kpi-card {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    text-align: center;
}
.kpi-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.55);
    text-transform: uppercase;
    letter-spacing: 0.4px;
    margin-bottom: 0.35rem;
}
.kpi-value {
    font-size: 1.75rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.95);
    line-height: 1.2;
}
.kpi-subtext {
    font-size: 0.75rem;
    color: rgba(255, 255, 255, 0.45);
    margin-top: 0.25rem;
}

/* Status badge styling */
.status-badge {
    display: inline-block;
    padding: 0.35rem 0.75rem;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.3px;
}
.status-on-track {
    background: rgba(34, 197, 94, 0.15);
    color: #22c55e;
    border: 1px solid rgba(34, 197, 94, 0.3);
}
.status-borderline {
    background: rgba(234, 179, 8, 0.15);
    color: #eab308;
    border: 1px solid rgba(234, 179, 8, 0.3);
}
.status-at-risk {
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    border: 1px solid rgba(239, 68, 68, 0.3);
}
.status-early-signal {
    background: rgba(249, 115, 22, 0.15);
    color: #f97316;
    border: 1px solid rgba(249, 115, 22, 0.3);
}

/* Button styling */
.stButton > button {
    border-radius: 8px !important;
    padding: 0.5rem 1.25rem !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}
.stButton > button[kind="primary"] {
    background: #ef4444 !important;
    border: none !important;
}
.stButton > button[kind="primary"]:hover {
    background: #dc2626 !important;
}

/* Empty state card */
.empty-state-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 2.5rem 2rem;
    text-align: center;
    max-width: 480px;
    margin: 2rem auto;
}
.empty-state-title {
    font-size: 1.25rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    margin-bottom: 0.5rem;
}
.empty-state-desc {
    font-size: 0.9rem;
    color: rgba(255, 255, 255, 0.55);
    margin-bottom: 1.5rem;
    line-height: 1.5;
}

/* Setup checklist card */
.setup-card {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
}
.setup-card-header {
    font-size: 0.95rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    margin-bottom: 0.75rem;
}
.setup-item {
    display: flex;
    align-items: center;
    padding: 0.4rem 0;
    font-size: 0.9rem;
}
.setup-item-done {
    color: rgba(255, 255, 255, 0.45);
    text-decoration: line-through;
}
.setup-item-pending {
    color: rgba(255, 255, 255, 0.85);
}

/* Action list styling */
.action-list {
    padding: 0;
    margin: 0;
}
.action-item {
    padding: 0.6rem 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.action-item:last-child {
    border-bottom: none;
}
.action-number {
    display: inline-block;
    width: 1.5rem;
    color: rgba(255, 255, 255, 0.4);
    font-size: 0.85rem;
}
.action-label {
    display: inline-block;
    background: rgba(255, 255, 255, 0.08);
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.6);
    margin-right: 0.4rem;
    text-transform: uppercase;
}
.action-text {
    color: rgba(255, 255, 255, 0.9);
    font-size: 0.9rem;
}
.action-detail {
    margin-left: 1.5rem;
    font-size: 0.8rem;
    color: rgba(255, 255, 255, 0.45);
    margin-top: 0.2rem;
}

/* Table styling */
.stDataFrame {
    border-radius: 8px !important;
    overflow: hidden !important;
}

/* Spacing between sections */
.section-spacer {
    margin-top: 2rem;
}

/* Confidence indicator */
.confidence-indicator {
    font-size: 0.8rem;
    color: rgba(255, 255, 255, 0.5);
    margin-top: 0.5rem;
}
</style>
"""


def inject_css():
    """Inject global CSS styles into the Streamlit app."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_card(title: str, content_fn, card_class: str = "saas-card"):
    """
    Render content inside a styled card container.

    Args:
        title: Card header title (None to skip header)
        content_fn: Function that renders the card content
        card_class: CSS class for the card
    """
    html_start = f'<div class="{card_class}">'
    if title:
        html_start += f'<div class="saas-card-header">{title}</div>'

    st.markdown(html_start, unsafe_allow_html=True)
    content_fn()
    st.markdown('</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, subtext: str = None) -> str:
    """
    Generate HTML for a KPI metric card.

    Args:
        label: Small label text above the value
        value: Large main value
        subtext: Optional small text below the value

    Returns:
        HTML string for the metric card
    """
    subtext_html = f'<div class="kpi-subtext">{subtext}</div>' if subtext else ''
    return f'''
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {subtext_html}
    </div>
    '''


def render_kpi_row(metrics: list):
    """
    Render a row of KPI metric cards.

    Args:
        metrics: List of dicts with keys: label, value, subtext (optional)
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            st.markdown(
                metric_card(m['label'], m['value'], m.get('subtext')),
                unsafe_allow_html=True
            )


def status_badge(status: str) -> str:
    """
    Generate HTML for a status badge.

    Args:
        status: One of 'on_track', 'borderline', 'at_risk', 'early_signal'

    Returns:
        HTML string for the status badge
    """
    status_map = {
        'on_track': ('ON TRACK', 'status-on-track'),
        'borderline': ('BORDERLINE', 'status-borderline'),
        'at_risk': ('AT RISK', 'status-at-risk'),
        'early_signal': ('EARLY SIGNAL', 'status-early-signal'),
    }
    text, css_class = status_map.get(status, ('UNKNOWN', ''))
    return f'<span class="status-badge {css_class}">{text}</span>'


def render_empty_state(title: str, description: str, button_label: str, on_click_key: str):
    """
    Render a centered empty state card with CTA button.

    Args:
        title: Main title text
        description: Description text (1-2 lines)
        button_label: Text for the CTA button
        on_click_key: Session state key to set True on click

    Returns:
        True if button was clicked, False otherwise
    """
    st.markdown(f'''
    <div class="empty-state-card">
        <div class="empty-state-title">{title}</div>
        <div class="empty-state-desc">{description}</div>
    </div>
    ''', unsafe_allow_html=True)

    # Center the button
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button(button_label, type="primary", use_container_width=True, key=f"empty_state_{on_click_key}"):
            st.session_state[on_click_key] = True
            return True
    return False


def render_setup_checklist(items: list):
    """
    Render a setup checklist card.

    Args:
        items: List of dicts with keys: label, done, button_key (optional)

    Returns:
        Key of clicked button if any, else None
    """
    st.markdown('<div class="setup-card">', unsafe_allow_html=True)
    st.markdown('<div class="setup-card-header">Complete Setup</div>', unsafe_allow_html=True)

    clicked = None
    for item in items:
        if item['done']:
            st.markdown(f'''
            <div class="setup-item setup-item-done">
                <span style="margin-right: 0.5rem;">&#10003;</span> {item['label']}
            </div>
            ''', unsafe_allow_html=True)
        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f'''
                <div class="setup-item setup-item-pending">
                    <span style="margin-right: 0.5rem; opacity: 0.4;">&#9675;</span> {item['label']}
                </div>
                ''', unsafe_allow_html=True)
            with col2:
                if st.button("Add", key=item.get('button_key', f"setup_{item['label']}"), use_container_width=True):
                    clicked = item.get('button_key')

    st.markdown('</div>', unsafe_allow_html=True)
    return clicked


def render_action_list(tasks: list, max_items: int = 5):
    """
    Render a styled action list.

    Args:
        tasks: List of task dicts with: task_type, title, detail, est_minutes (optional)
        max_items: Maximum number of items to show
    """
    task_type_labels = {
        'assessment_due': 'Due',
        'timed_attempt': 'Practice',
        'review_topic': 'Review',
        'do_exercises': 'Exercises',
        'setup_missing': 'Setup'
    }

    st.markdown('<div class="action-list">', unsafe_allow_html=True)

    for i, task in enumerate(tasks[:max_items]):
        label = task_type_labels.get(task['task_type'], '')
        time_info = f" ({task['est_minutes']}min)" if task.get('est_minutes') else ""

        st.markdown(f'''
        <div class="action-item">
            <span class="action-number">{i+1}.</span>
            <span class="action-label">{label}</span>
            <span class="action-text">{task['title']}{time_info}</span>
            <div class="action-detail">{task['detail']}</div>
        </div>
        ''', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


def section_header(title: str, margin_top: bool = True):
    """Render a section header with consistent styling."""
    margin = "margin-top: 2rem;" if margin_top else ""
    st.markdown(f'<h3 style="{margin}">{title}</h3>', unsafe_allow_html=True)


def card_start(title: str = None):
    """Start a card container. Must be paired with card_end()."""
    html = '<div class="saas-card">'
    if title:
        html += f'<div class="saas-card-header">{title}</div>'
    st.markdown(html, unsafe_allow_html=True)


def card_end():
    """End a card container started with card_start()."""
    st.markdown('</div>', unsafe_allow_html=True)
