"""
PDF Topic Extraction Module (IMPROVED VERSION)
Extracts ONLY high-quality, course-level topics from PDF lecture slides.
Designed to output 8-25 topics per deck, not hundreds.
"""

import re
import math
from typing import List, Dict, Tuple
from collections import Counter, defaultdict

# Try to import optional dependencies
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False


def normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_boilerplate(text: str) -> bool:
    """
    Check if text is boilerplate (course name, professor, university, etc.).
    REQUIREMENT A: Reject common boilerplate patterns.
    """
    boilerplate_patterns = [
        # Generic structural markers
        r'^slide\s*\d*$',
        r'^page\s*\d*$',
        r'^chapter\s*\d*$',
        r'^section\s*\d*$',
        r'^lecture\s*\d*$',
        r'^part\s*\d*$',
        r'^unit\s*\d*$',

        # Table of contents / navigation
        r'^contents?$',
        r'^table\s*of\s*contents$',
        r'^outline$',
        r'^agenda$',
        r'^overview$',
        r'^roadmap$',
        r'^todays?\s*(lecture|class|agenda|topic)s?$',

        # Intro/conclusion markers
        r'^introduction$',
        r'^intro$',
        r'^conclusion$',
        r'^conclusions?$',
        r'^summary$',
        r'^recap$',
        r'^review$',

        # Q&A and ending
        r'^questions?\??$',
        r'^q\s*a\s*$',
        r'^thank\s*you.*$',
        r'^thanks.*$',
        r'^the\s*end$',

        # References
        r'^references?$',
        r'^bibliography$',
        r'^further\s*reading$',
        r'^resources?$',

        # Frankfurt School specific (as mentioned in requirements)
        r'.*frankfurt\s*school.*',
        r'.*fs\s*frankfurt.*',

        # Generic course markers
        r'.*university.*',
        r'.*professor.*',
        r'.*instructor.*',
        r'.*dr\s*\w+.*',
        r'.*ph\.?d\.?.*',
        r'.*department\s*of.*',
        r'.*course\s*code.*',
        r'.*course\s*number.*',
        r'.*semester.*',
        r'.*spring\s*\d{4}.*',
        r'.*fall\s*\d{4}.*',
        r'.*winter\s*\d{4}.*',
        r'.*academic\s*year.*',
    ]

    normalized = normalize_text(text)

    for pattern in boilerplate_patterns:
        if re.match(pattern, normalized):
            return True

    return False


def is_valid_candidate_line(text: str) -> bool:
    """
    REQUIREMENT A: Validate candidate lines.
    Reject if:
    - length < 6 or > 80
    - contains mostly digits/symbols
    - is boilerplate
    """
    text = text.strip()

    # Length check
    if len(text) < 6 or len(text) > 80:
        return False

    # Check if mostly digits/symbols
    alphanumeric_chars = sum(c.isalnum() for c in text)
    if alphanumeric_chars < len(text) * 0.5:  # Less than 50% alphanumeric
        return False

    # Check for page numbers
    if re.match(r'^[\d\s\-/]+$', text):
        return False

    # Boilerplate check
    if is_boilerplate(text):
        return False

    return True


def extract_page_candidates(page, page_num: int) -> List[Dict]:
    """
    Extract high-signal topic candidates from a single PDF page.
    REQUIREMENT A: Only consider lines with MAX font size on the page.

    Returns list of dicts with: text, font_size, page_num
    """
    candidates = []

    # Get text blocks with font information
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

    # Collect all spans with their font sizes
    all_spans = []
    for block in blocks:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            line_text = ""
            max_font_size = 0
            for span in line["spans"]:
                line_text += span["text"]
                max_font_size = max(max_font_size, span["size"])

            line_text = line_text.strip()
            if line_text and len(line_text) > 2:
                all_spans.append({
                    "text": line_text,
                    "font_size": max_font_size,
                    "y_pos": line["bbox"][1]  # Top position
                })

    if not all_spans:
        return []

    # Find the MAXIMUM font size on this page
    max_font = max(s["font_size"] for s in all_spans)

    # REQUIREMENT A: Only take lines with the MAX font size (within 5% tolerance)
    # This is key to reducing noise - we only want the biggest titles
    max_font_candidates = [
        s for s in all_spans
        if s["font_size"] >= max_font * 0.95  # Within 5% of max
    ]

    # Filter footer/header by position (skip bottom 10% and top 5% of page)
    page_height = page.rect.height
    max_font_candidates = [
        s for s in max_font_candidates
        if page_height * 0.05 < s["y_pos"] < page_height * 0.90
    ]

    for span in max_font_candidates:
        text = span["text"]

        # Validate the candidate
        if is_valid_candidate_line(text):
            candidates.append({
                "text": text,
                "font_size": span["font_size"],
                "page_num": page_num
            })

    return candidates


def extract_all_candidates(pdf_bytes: bytes, filename: str) -> Tuple[List[Dict], int]:
    """
    Extract all candidate topics from a PDF file.

    Returns:
        Tuple of (candidates, num_pages)
    """
    if not HAS_PYMUPDF:
        raise ImportError("PyMuPDF (fitz) is required. Install with: pip install pymupdf")

    candidates = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    num_pages = len(doc)

    for page_num in range(num_pages):
        page = doc[page_num]
        page_candidates = extract_page_candidates(page, page_num + 1)

        for cand in page_candidates:
            candidates.append({
                "topic_name": cand["text"],
                "source_file": filename,
                "font_size": cand["font_size"],
                "page_num": cand["page_num"]
            })

    doc.close()
    return candidates, num_pages


def filter_repeated_headers(candidates: List[Dict], total_pages: int) -> List[Dict]:
    """
    REQUIREMENT A: Remove candidates that appear on > 10% of pages (repeated headers).
    Does NOT deduplicate - keeps all instances but marks occurrence count.
    """
    if not candidates:
        return []

    # Count occurrences per normalized text across pages
    normalized_page_sets = defaultdict(set)

    for cand in candidates:
        normalized = normalize_text(cand["topic_name"])
        normalized_page_sets[normalized].add(cand["page_num"])

    # Filter out topics appearing on > 10% of pages
    max_pages = max(1, int(total_pages * 0.10))

    # Create set of normalized topics to exclude
    excluded_normalized = set()
    for normalized, pages in normalized_page_sets.items():
        if len(pages) > max_pages:
            excluded_normalized.add(normalized)

    # Filter candidates, keeping all instances of valid topics
    filtered = []
    for cand in candidates:
        normalized = normalize_text(cand["topic_name"])
        if normalized not in excluded_normalized:
            # Add occurrence count metadata
            cand_copy = cand.copy()
            cand_copy["occurrence_count"] = len(normalized_page_sets[normalized])
            filtered.append(cand_copy)

    return filtered


def filter_by_frequency(candidates: List[Dict], total_pages: int) -> List[Dict]:
    """
    REQUIREMENT B: Keep only candidates that appear at least:
    - max(2 occurrences, 3% of pages)

    This kills one-off slide titles and promotes section-level topics.
    """
    if not candidates:
        return []

    min_occurrences = max(2, math.ceil(total_pages * 0.03))

    # Group candidates by normalized text
    normalized_groups = defaultdict(list)
    for cand in candidates:
        normalized = normalize_text(cand["topic_name"])
        normalized_groups[normalized].append(cand)

    # Filter by frequency
    filtered = []
    for normalized, group in normalized_groups.items():
        occurrence_count = len(set(c["page_num"] for c in group))

        if occurrence_count >= min_occurrences:
            # Keep the best representative from this group
            best = max(group, key=lambda c: (c.get("font_size", 0), len(c["topic_name"])))
            best["occurrence_count"] = occurrence_count
            filtered.append(best)

    return filtered


def cluster_similar_topics(candidates: List[Dict], similarity_threshold: float = 90.0) -> List[Dict]:
    """
    REQUIREMENT C: Cluster and merge similar candidates using rapidfuzz.
    - Normalize strings (lowercase, remove punctuation, collapse spaces)
    - Cluster candidates with similarity >= 90
    - For each cluster, choose the longest informative string (but <= 80 chars)
    - Remove candidates that are strict substrings of another topic
    """
    if not HAS_RAPIDFUZZ or not candidates:
        return candidates

    merged = []
    used_indices = set()

    for i, cand1 in enumerate(candidates):
        if i in used_indices:
            continue

        cluster = [cand1]
        used_indices.add(i)

        # Find all similar candidates
        for j, cand2 in enumerate(candidates[i+1:], start=i+1):
            if j in used_indices:
                continue

            norm1 = normalize_text(cand1["topic_name"])
            norm2 = normalize_text(cand2["topic_name"])

            similarity = fuzz.ratio(norm1, norm2)

            if similarity >= similarity_threshold:
                cluster.append(cand2)
                used_indices.add(j)

        # Choose best representative from cluster
        # Prefer: most frequent, then longest (up to 80 chars), then highest font size
        best = max(cluster, key=lambda c: (
            c.get("occurrence_count", 1),
            min(len(c["topic_name"]), 80),
            c.get("font_size", 0)
        ))

        # Aggregate metadata from cluster
        best["occurrence_count"] = sum(c.get("occurrence_count", 1) for c in cluster)
        best["avg_font_size"] = sum(c.get("font_size", 0) for c in cluster) / len(cluster)

        merged.append(best)

    # REQUIREMENT C: Remove strict substrings
    final = []
    for i, cand1 in enumerate(merged):
        is_substring = False
        norm1 = normalize_text(cand1["topic_name"])

        for j, cand2 in enumerate(merged):
            if i == j:
                continue
            norm2 = normalize_text(cand2["topic_name"])

            # Check if norm1 is a strict substring of norm2
            if norm1 in norm2 and norm1 != norm2:
                is_substring = True
                break

        if not is_substring:
            final.append(cand1)

    return final


def merge_hierarchical_topics(candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    REQUIREMENT E: Hierarchical topic merge.
    Detect patterns like:
    - "Oligopoly I: Cournot"
    - "Oligopoly II: Bertrand"
    Merge to parent "Oligopoly" with children as subtopics.

    Returns:
        Tuple of (main_topics, subtopics)
    """
    # Pattern: "ParentTopic [Roman/Number]: Subtitle"
    hierarchical_pattern = re.compile(
        r'^(.+?)\s+(?:I{1,3}|IV|V|VI{0,3}|\d+|[A-Z])[\s:.\-]+(.+)$',
        re.IGNORECASE
    )

    parent_groups = defaultdict(list)
    standalone = []

    for cand in candidates:
        text = cand["topic_name"].strip()
        match = hierarchical_pattern.match(text)

        if match:
            parent_name = match.group(1).strip()
            subtitle = match.group(2).strip()

            # Create parent if not exists
            parent_key = normalize_text(parent_name)
            parent_groups[parent_key].append({
                "parent_name": parent_name,
                "subtitle": subtitle,
                "original": cand
            })
        else:
            standalone.append(cand)

    # Build main topics and subtopics
    main_topics = []
    all_subtopics = []

    for parent_key, children in parent_groups.items():
        # Create parent topic
        parent_name = children[0]["parent_name"]  # Use first occurrence's formatting

        # Aggregate stats from children
        total_occurrences = sum(c["original"].get("occurrence_count", 1) for c in children)
        avg_font = sum(c["original"].get("avg_font_size", c["original"].get("font_size", 0)) for c in children) / len(children)

        parent_topic = {
            "topic_name": parent_name,
            "occurrence_count": total_occurrences,
            "avg_font_size": avg_font,
            "has_subtopics": True,
            "num_subtopics": len(children)
        }

        # Add source_file if available
        if "source_file" in children[0]["original"]:
            parent_topic["source_file"] = children[0]["original"]["source_file"]

        main_topics.append(parent_topic)

        # Store subtopics separately
        for child in children:
            subtopic = child["original"].copy()
            subtopic["parent_topic"] = parent_name
            subtopic["is_subtopic"] = True
            all_subtopics.append(subtopic)

    # Add standalone topics to main
    for topic in standalone:
        topic["has_subtopics"] = False
        main_topics.append(topic)

    return main_topics, all_subtopics


def rank_and_cap_topics(candidates: List[Dict], total_pages: int) -> List[Dict]:
    """
    REQUIREMENT D: Rank topics by importance and cap output.

    Ranking criteria:
    - Frequency across pages (descending)
    - Average font size (descending)

    Output cap:
    - N = min(25, max(8, round(sqrt(num_pages) * 3)))
    """
    if not candidates:
        return []

    # Sort by frequency (descending), then by font size (descending)
    ranked = sorted(
        candidates,
        key=lambda c: (
            -c.get("occurrence_count", 1),
            -c.get("avg_font_size", c.get("font_size", 0))
        )
    )

    # Calculate adaptive cap
    cap = min(25, max(8, round(math.sqrt(total_pages) * 3)))

    return ranked[:cap]


def extract_topic_candidates(pdf_files: List[Tuple[bytes, str]]) -> Tuple[List[Dict], Dict]:
    """
    MAIN ENTRY POINT: Extract high-quality topic candidates from PDF files.

    This implements ALL requirements A-E:
    A) High-signal line extraction with aggressive filtering
    B) Frequency-based filtering (min 2 occurrences or 3% of pages)
    C) Similarity clustering with rapidfuzz (90% threshold)
    D) Ranking and output capping (8-25 topics)
    E) Hierarchical topic merging

    Args:
        pdf_files: List of (pdf_bytes, filename) tuples

    Returns:
        Tuple of (final_topics, stats_dict)
    """
    all_candidates = []
    total_pages = 0

    # Extract candidates from all PDFs
    for pdf_bytes, filename in pdf_files:
        try:
            candidates, num_pages = extract_all_candidates(pdf_bytes, filename)
            all_candidates.extend(candidates)
            total_pages += num_pages
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue

    raw_count = len(all_candidates)

    # REQUIREMENT A: Filter repeated headers (> 10% of pages)
    after_header_filter = filter_repeated_headers(all_candidates, total_pages)
    header_filter_count = len(after_header_filter)

    # REQUIREMENT B: Filter by frequency (section-level topics)
    after_frequency_filter = filter_by_frequency(after_header_filter, total_pages)
    frequency_filter_count = len(after_frequency_filter)

    # REQUIREMENT C: Cluster similar topics
    after_clustering = cluster_similar_topics(after_frequency_filter, similarity_threshold=90.0)
    cluster_count = len(after_clustering)

    # REQUIREMENT E: Hierarchical merging
    main_topics, subtopics = merge_hierarchical_topics(after_clustering)
    hierarchical_count = len(main_topics)

    # REQUIREMENT D: Rank and cap
    final_topics = rank_and_cap_topics(main_topics, total_pages)
    final_count = len(final_topics)

    # REQUIREMENT F: Statistics for UI
    stats = {
        "files_processed": len(pdf_files),
        "total_pages": total_pages,
        "raw_candidates": raw_count,
        "after_header_filter": header_filter_count,
        "after_frequency_filter": frequency_filter_count,
        "after_clustering": cluster_count,
        "after_hierarchical_merge": hierarchical_count,
        "final_topics": final_count,
        "subtopics": subtopics,  # Store for optional display
        "adaptive_cap": min(25, max(8, round(math.sqrt(total_pages) * 3)))
    }

    return final_topics, stats


# Legacy compatibility wrapper
def extract_and_process_topics(pdf_files: List[Tuple[bytes, str]]) -> Tuple[List[Dict], Dict]:
    """
    Legacy compatibility wrapper.
    Calls the new extract_topic_candidates function.
    """
    return extract_topic_candidates(pdf_files)


def postprocess_topics(candidates: List[Dict], show_subtopics: bool = False) -> List[Dict]:
    """
    Optional post-processing for UI display.

    Args:
        candidates: Final topics from extract_topic_candidates
        show_subtopics: If True, expand hierarchical topics to show subtopics

    Returns:
        Topics ready for display
    """
    if not show_subtopics:
        return candidates

    # This would be called with the subtopics from stats if needed
    # For now, just return candidates as-is
    return candidates
