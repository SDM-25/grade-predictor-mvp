"""
UI Components and Styling for Exam Readiness Predictor
Modern SaaS-style dashboard components
v2.1 - Added quick navigation and dashboard sections
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

/* Responsive Typography */
@media (max-width: 768px) {
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.05rem !important; }
    p, .stMarkdown { font-size: 0.9rem !important; }
}
@media (max-width: 480px) {
    h1 { font-size: 1.3rem !important; }
    h2 { font-size: 1.1rem !important; }
    h3 { font-size: 1rem !important; }
}

/* Card styling */
.saas-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.saas-card:hover {
    border-color: rgba(255, 255, 255, 0.15);
}
.saas-card-header {
    font-size: 0.85rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.6);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.75rem;
}

/* Responsive Cards */
@media (max-width: 768px) {
    .saas-card {
        padding: 1rem;
        border-radius: 10px;
    }
}
@media (max-width: 480px) {
    .saas-card {
        padding: 0.85rem;
        border-radius: 8px;
        margin-bottom: 0.75rem;
    }
}

/* KPI Card styling */
.kpi-card {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    text-align: center;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
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

/* Color-coded KPI Card variants */
.kpi-card-success {
    background: rgba(34, 197, 94, 0.08);
    border-color: rgba(34, 197, 94, 0.25);
}
.kpi-card-success:hover {
    border-color: rgba(34, 197, 94, 0.4);
}
.kpi-card-success .kpi-value {
    color: #22c55e;
}

.kpi-card-warning {
    background: rgba(234, 179, 8, 0.08);
    border-color: rgba(234, 179, 8, 0.25);
}
.kpi-card-warning:hover {
    border-color: rgba(234, 179, 8, 0.4);
}
.kpi-card-warning .kpi-value {
    color: #eab308;
}

.kpi-card-danger {
    background: rgba(239, 68, 68, 0.08);
    border-color: rgba(239, 68, 68, 0.25);
}
.kpi-card-danger:hover {
    border-color: rgba(239, 68, 68, 0.4);
}
.kpi-card-danger .kpi-value {
    color: #ef4444;
}

.kpi-card-info {
    background: rgba(59, 130, 246, 0.08);
    border-color: rgba(59, 130, 246, 0.25);
}
.kpi-card-info:hover {
    border-color: rgba(59, 130, 246, 0.4);
}
.kpi-card-info .kpi-value {
    color: #3b82f6;
}

.kpi-card-orange {
    background: rgba(249, 115, 22, 0.08);
    border-color: rgba(249, 115, 22, 0.25);
}
.kpi-card-orange:hover {
    border-color: rgba(249, 115, 22, 0.4);
}
.kpi-card-orange .kpi-value {
    color: #f97316;
}

/* Responsive KPI Cards */
@media (max-width: 768px) {
    .kpi-card {
        padding: 0.85rem 1rem;
    }
    .kpi-value {
        font-size: 1.5rem;
    }
    .kpi-label {
        font-size: 0.7rem;
    }
}
@media (max-width: 480px) {
    .kpi-card {
        padding: 0.75rem 0.85rem;
        border-radius: 8px;
    }
    .kpi-value {
        font-size: 1.3rem;
    }
    .kpi-label {
        font-size: 0.65rem;
        letter-spacing: 0.3px;
    }
    .kpi-subtext {
        font-size: 0.7rem;
    }
}

/* Status badge styling */
.status-badge {
    display: inline-block;
    padding: 0.35rem 0.75rem;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.3px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.status-badge:hover {
    transform: scale(1.02);
}
.status-on-track {
    background: rgba(34, 197, 94, 0.15);
    color: #22c55e;
    border: 1px solid rgba(34, 197, 94, 0.3);
    box-shadow: 0 0 8px rgba(34, 197, 94, 0.1);
}
.status-borderline {
    background: rgba(234, 179, 8, 0.15);
    color: #eab308;
    border: 1px solid rgba(234, 179, 8, 0.3);
    box-shadow: 0 0 8px rgba(234, 179, 8, 0.1);
}
.status-at-risk {
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    border: 1px solid rgba(239, 68, 68, 0.3);
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.1);
}
.status-early-signal {
    background: rgba(249, 115, 22, 0.15);
    color: #f97316;
    border: 1px solid rgba(249, 115, 22, 0.3);
    box-shadow: 0 0 8px rgba(249, 115, 22, 0.1);
}

/* Responsive Status Badges */
@media (max-width: 480px) {
    .status-badge {
        padding: 0.25rem 0.5rem;
        font-size: 0.7rem;
        border-radius: 4px;
    }
}

/* Button styling - Dark SaaS style with polished animations */
.stButton > button {
    border-radius: 8px !important;
    padding: 0.5rem 1.25rem !important;
    font-weight: 500 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    position: relative !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    border-color: rgba(255, 255, 255, 0.25) !important;
    box-shadow:
        0 4px 12px rgba(0, 0, 0, 0.3),
        0 0 20px rgba(255, 255, 255, 0.05) !important;
}
.stButton > button:active {
    transform: translateY(0) scale(0.98) !important;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2) !important;
    transition: all 0.1s ease !important;
}

/* Primary button variant - Red accent with glow */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
    box-shadow: 0 2px 8px rgba(239, 68, 68, 0.15) !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #f87171 0%, #ef4444 100%) !important;
    border-color: rgba(248, 113, 113, 0.5) !important;
    box-shadow:
        0 6px 20px rgba(239, 68, 68, 0.35),
        0 0 30px rgba(239, 68, 68, 0.15),
        inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}
.stButton > button[kind="primary"]:active {
    background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
    box-shadow:
        0 2px 8px rgba(239, 68, 68, 0.25),
        inset 0 2px 4px rgba(0, 0, 0, 0.1) !important;
}

/* Form submit buttons - same primary styling */
.stFormSubmitButton > button {
    border-radius: 8px !important;
    padding: 0.5rem 1.25rem !important;
    font-weight: 500 !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
    box-shadow: 0 2px 8px rgba(239, 68, 68, 0.15) !important;
}
.stFormSubmitButton > button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    background: linear-gradient(135deg, #f87171 0%, #ef4444 100%) !important;
    border-color: rgba(248, 113, 113, 0.5) !important;
    box-shadow:
        0 6px 20px rgba(239, 68, 68, 0.35),
        0 0 30px rgba(239, 68, 68, 0.15),
        inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}
.stFormSubmitButton > button[kind="primary"]:active {
    transform: translateY(0) scale(0.98) !important;
    background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
    box-shadow:
        0 2px 8px rgba(239, 68, 68, 0.25),
        inset 0 2px 4px rgba(0, 0, 0, 0.1) !important;
    transition: all 0.1s ease !important;
}

/* Responsive Buttons */
@media (max-width: 480px) {
    .stButton > button {
        padding: 0.45rem 1rem !important;
        font-size: 0.85rem !important;
    }
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

/* Responsive Empty State */
@media (max-width: 480px) {
    .empty-state-card {
        padding: 1.75rem 1.25rem;
        margin: 1rem auto;
    }
    .empty-state-title {
        font-size: 1.1rem;
    }
    .empty-state-desc {
        font-size: 0.85rem;
    }
}

/* Setup checklist card */
.setup-card {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
    transition: border-color 0.2s ease;
}
.setup-card:hover {
    border-color: rgba(239, 68, 68, 0.35);
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
    transition: background-color 0.15s ease;
}
.setup-item-done {
    color: #22c55e;
    text-decoration: none;
    opacity: 0.7;
}
.setup-item-pending {
    color: rgba(255, 255, 255, 0.85);
}

/* Responsive Setup Card */
@media (max-width: 480px) {
    .setup-card {
        padding: 1rem;
    }
    .setup-item {
        font-size: 0.85rem;
    }
}

/* Action list styling */
.action-list {
    padding: 0;
    margin: 0;
}
.action-item {
    padding: 0.6rem 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    transition: background-color 0.15s ease;
}
.action-item:hover {
    background-color: rgba(255, 255, 255, 0.02);
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
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    margin-right: 0.4rem;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}

/* Color-coded action labels by type */
.action-label-due {
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    border: 1px solid rgba(239, 68, 68, 0.3);
}
.action-label-practice {
    background: rgba(59, 130, 246, 0.15);
    color: #3b82f6;
    border: 1px solid rgba(59, 130, 246, 0.3);
}
.action-label-review {
    background: rgba(168, 85, 247, 0.15);
    color: #a855f7;
    border: 1px solid rgba(168, 85, 247, 0.3);
}
.action-label-exercises {
    background: rgba(34, 197, 94, 0.15);
    color: #22c55e;
    border: 1px solid rgba(34, 197, 94, 0.3);
}
.action-label-setup {
    background: rgba(234, 179, 8, 0.15);
    color: #eab308;
    border: 1px solid rgba(234, 179, 8, 0.3);
}
.action-label-default {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.12);
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

/* Responsive Action List */
@media (max-width: 480px) {
    .action-item {
        padding: 0.5rem 0;
    }
    .action-label {
        font-size: 0.6rem;
        padding: 0.1rem 0.3rem;
    }
    .action-text {
        font-size: 0.85rem;
    }
    .action-detail {
        font-size: 0.75rem;
        margin-left: 1.25rem;
    }
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

/* Quick Navigation Bar - Compact jump links */
.quick-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.6rem 0;
    margin: 0.75rem 0 1.25rem 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.quick-nav-label {
    display: flex;
    align-items: center;
    font-size: 0.7rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.4);
    text-transform: uppercase;
    letter-spacing: 0.3px;
    margin-right: 0.25rem;
}
.quick-nav-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.35rem 0.7rem;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.65);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    text-decoration: none;
}
.quick-nav-btn:hover {
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.15);
    color: rgba(255, 255, 255, 0.9);
    transform: translateY(-1px);
}
.quick-nav-btn:active {
    transform: translateY(0);
}
.quick-nav-btn-icon {
    font-size: 0.8rem;
    opacity: 0.8;
}

/* Dashboard Section Card - Enhanced visual separation */
.dashboard-section {
    background: rgba(255, 255, 255, 0.015);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
    padding: 1.1rem 1.25rem;
    margin-bottom: 1.75rem;
    transition: border-color 0.2s ease;
}
.dashboard-section:hover {
    border-color: rgba(255, 255, 255, 0.1);
}

/* Primary Section - For Recommended Actions (emphasized) */
.dashboard-section-primary {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.06) 0%, rgba(59, 130, 246, 0.02) 100%);
    border: 1px solid rgba(59, 130, 246, 0.2);
    border-radius: 10px;
    padding: 1.1rem 1.25rem;
    margin-bottom: 1.75rem;
    box-shadow: 0 2px 8px rgba(59, 130, 246, 0.05);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.dashboard-section-primary:hover {
    border-color: rgba(59, 130, 246, 0.3);
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
}

/* Section Header inside cards */
.section-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    margin-bottom: 0.9rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-title-primary {
    font-size: 1rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.95);
    margin-bottom: 0.9rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(59, 130, 246, 0.15);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-title-icon {
    font-size: 1rem;
    opacity: 0.85;
}

/* Collapsible section styling */
.collapsible-section {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
    margin-bottom: 1rem;
}

/* Sidebar improvements - Clear visual grouping */
.sidebar-section {
    padding: 0.75rem 0;
}
.sidebar-section-header {
    font-size: 0.65rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.45);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-bottom: 0.6rem;
    padding-left: 2px;
}
.sidebar-divider {
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    margin: 1rem 0;
}
/* Sidebar course selection group */
.sidebar-course-group {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 0.75rem;
    margin-bottom: 0.75rem;
}
/* Sidebar add course group - visually distinct */
.sidebar-add-group {
    background: rgba(255, 255, 255, 0.01);
    border: 1px dashed rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 0.75rem;
    margin-top: 0.5rem;
}
.sidebar-add-group:hover {
    border-color: rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.02);
}

@media (max-width: 768px) {
    .quick-nav {
        gap: 0.4rem;
        padding: 0.5rem 0;
    }
    .quick-nav-btn {
        padding: 0.35rem 0.65rem;
        font-size: 0.75rem;
    }
    .dashboard-section, .dashboard-section-primary {
        padding: 1rem;
        margin-bottom: 1rem;
    }
}
@media (max-width: 480px) {
    .quick-nav-btn {
        padding: 0.3rem 0.5rem;
        font-size: 0.7rem;
    }
    .dashboard-section, .dashboard-section-primary {
        padding: 0.85rem;
        border-radius: 8px;
    }
}

/* Confidence indicator */
.confidence-indicator {
    font-size: 0.8rem;
    color: rgba(255, 255, 255, 0.5);
    margin-top: 0.5rem;
}

/* Progress indicator colors */
.progress-high {
    color: #22c55e;
}
.progress-medium {
    color: #eab308;
}
.progress-low {
    color: #ef4444;
}

/* Urgency indicators */
.urgency-critical {
    color: #ef4444;
    font-weight: 600;
}
.urgency-warning {
    color: #eab308;
    font-weight: 500;
}
.urgency-normal {
    color: #22c55e;
}

/* Global responsive layout helpers */
@media (max-width: 768px) {
    /* Stack columns on tablet */
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
    }
    .section-spacer {
        margin-top: 1.5rem;
    }
}
@media (max-width: 480px) {
    /* Tighter spacing on mobile */
    .section-spacer {
        margin-top: 1rem;
    }
    /* Better touch targets */
    .stButton > button {
        min-height: 44px !important;
    }
    .stSelectbox > div > div {
        min-height: 44px !important;
    }
}

/* Smooth transitions for all interactive elements */
* {
    -webkit-tap-highlight-color: transparent;
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


def metric_card(label: str, value: str, subtext: str = None, variant: str = None) -> str:
    """
    Generate HTML for a KPI metric card.

    Args:
        label: Small label text above the value
        value: Large main value
        subtext: Optional small text below the value
        variant: Color variant - 'success', 'warning', 'danger', 'info', 'orange', or None

    Returns:
        HTML string for the metric card
    """
    subtext_html = f'<div class="kpi-subtext">{subtext}</div>' if subtext else ''
    variant_class = f' kpi-card-{variant}' if variant else ''
    return f'''
    <div class="kpi-card{variant_class}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {subtext_html}
    </div>
    '''


def render_kpi_row(metrics: list):
    """
    Render a row of KPI metric cards.

    Args:
        metrics: List of dicts with keys: label, value, subtext (optional), variant (optional)
                 variant can be: 'success', 'warning', 'danger', 'info', 'orange'
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            st.markdown(
                metric_card(m['label'], m['value'], m.get('subtext'), m.get('variant')),
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
    Render a styled action list with color-coded labels.

    Args:
        tasks: List of task dicts with: task_type, title, detail, est_minutes (optional)
        max_items: Maximum number of items to show
    """
    # Map task types to labels and color classes
    task_type_config = {
        'assessment_due': ('Due', 'action-label-due'),
        'timed_attempt': ('Practice', 'action-label-practice'),
        'review_topic': ('Review', 'action-label-review'),
        'do_exercises': ('Exercises', 'action-label-exercises'),
        'setup_missing': ('Setup', 'action-label-setup')
    }

    st.markdown('<div class="action-list">', unsafe_allow_html=True)

    for i, task in enumerate(tasks[:max_items]):
        label, label_class = task_type_config.get(
            task['task_type'],
            (task['task_type'].replace('_', ' ').title(), 'action-label-default')
        )
        time_info = f" ({task['est_minutes']}min)" if task.get('est_minutes') else ""

        st.markdown(f'''
        <div class="action-item">
            <span class="action-number">{i+1}.</span>
            <span class="action-label {label_class}">{label}</span>
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


def render_quick_nav(sections: list):
    """
    Render a compact quick navigation bar with jump links to dashboard sections.

    Args:
        sections: List of dicts with keys: id, label, icon (optional)
    """
    buttons_html = '<span class="quick-nav-label">Jump to:</span>'
    for section in sections:
        icon_html = f'<span class="quick-nav-btn-icon">{section.get("icon", "")}</span>' if section.get("icon") else ""
        buttons_html += f'''
        <a href="#{section['id']}" class="quick-nav-btn">
            {icon_html}{section['label']}
        </a>
        '''

    st.markdown(f'''
    <div class="quick-nav">
        {buttons_html}
    </div>
    ''', unsafe_allow_html=True)


def dashboard_section_start(section_id: str, title: str, icon: str = None, primary: bool = False):
    """
    Start an enhanced dashboard section card with anchor.

    Args:
        section_id: HTML anchor ID for navigation
        title: Section title
        icon: Optional emoji icon
        primary: If True, uses emphasized primary styling
    """
    css_class = "dashboard-section-primary" if primary else "dashboard-section"
    title_class = "section-title-primary" if primary else "section-title"
    icon_html = f'<span class="section-title-icon">{icon}</span>' if icon else ""

    st.markdown(f'''
    <div id="{section_id}" class="{css_class}">
        <div class="{title_class}">{icon_html}{title}</div>
    ''', unsafe_allow_html=True)


def dashboard_section_end():
    """End a dashboard section started with dashboard_section_start()."""
    st.markdown('</div>', unsafe_allow_html=True)
