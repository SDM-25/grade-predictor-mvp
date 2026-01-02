# PDF Topic Extraction - Implementation Summary

## Overview
Successfully improved the PDF topic extraction algorithm to reduce output from **hundreds of topics to 8-25 high-quality, course-level topics** per lecture deck.

**Test Results:**
- **Before:** 188 raw candidates extracted
- **After:** 14 final topics (92.6% reduction)

---

## Implementation Details

### Requirement A: High-Signal Line Extraction
**Location:** `pdf_extractor.py:139-202` (`extract_page_candidates`)

**Changes:**
1. **Only extract MAX font size lines** (within 5% tolerance)
   - Old: Extracted fonts >= 70% of max → too permissive
   - New: Only fonts >= 95% of max → much more selective

2. **Position-based filtering** to remove headers/footers
   - Skip top 5% and bottom 10% of each page

3. **Enhanced boilerplate detection** (`is_boilerplate`, lines 34-106)
   - Added patterns for: Frankfurt School, universities, professors, semesters
   - Filters generic markers: Agenda, Outline, Q&A, Thank You, etc.

4. **Strict validation** (`is_valid_candidate_line`, lines 109-136)
   - Length: 6-80 characters only
   - Reject if < 50% alphanumeric (too many symbols)
   - Reject page numbers and purely numeric text

5. **Repeated header removal** (`filter_repeated_headers`, lines 235-269)
   - Remove candidates appearing on > 10% of pages
   - Old: Used 30% threshold → too lenient
   - New: 10% threshold → eliminates course names on every slide

---

### Requirement B: Frequency-Based Filtering
**Location:** `pdf_extractor.py:272-296` (`filter_by_frequency`)

**Changes:**
- **Minimum frequency requirement:** max(2 occurrences, 3% of pages)
- **Effect:** Kills one-off slide titles; promotes section-level topics
- **Example:**
  - 100-page deck: topic must appear on ≥ 3 pages
  - 30-page deck: topic must appear on ≥ 2 pages

---

### Requirement C: Similarity Clustering
**Location:** `pdf_extractor.py:299-367` (`cluster_similar_topics`)

**Changes:**
1. **Cluster similar topics** using rapidfuzz (90% similarity threshold)
   - Merges: "Market Equilibrium" ≈ "Market Equilibria"
   - Merges: "Game Theory" ≈ "Game Theories"

2. **Choose best representative** from each cluster:
   - Prioritize: most frequent → longest (up to 80 chars) → highest font size

3. **Remove substring topics**
   - "Oligopoly" is substring of "Oligopoly Models" → keep longer version

---

### Requirement D: Ranking and Output Capping
**Location:** `pdf_extractor.py:446-472` (`rank_and_cap_topics`)

**Changes:**
1. **Ranking criteria:**
   - Primary: Frequency (descending)
   - Secondary: Average font size (descending)

2. **Adaptive output cap:**
   ```
   cap = min(25, max(8, round(sqrt(num_pages) * 3)))
   ```
   - 10 pages → cap = 9
   - 25 pages → cap = 15
   - 100 pages → cap = 25 (max)
   - 200 pages → cap = 25 (max)

**Effect:** Automatically scales to deck size while staying in 8-25 range

---

### Requirement E: Hierarchical Topic Merging
**Location:** `pdf_extractor.py:370-443` (`merge_hierarchical_topics`)

**Changes:**
- **Detects patterns** like:
  - "Oligopoly I: Cournot"
  - "Oligopoly II: Bertrand"
  - "Module 1: Introduction"

- **Merges to parent topic:**
  - Parent: "Oligopoly" (or "Module")
  - Subtopics: stored separately for optional display

- **Pattern matching:** Roman numerals (I-VI), numbers (1-9), single letters (A-Z)

---

### Requirement F: UI Improvements
**Location:** `app.py:1646-1685`

**Changes:**
1. **Extraction Summary** now shows:
   - Files Processed
   - Pages Scanned
   - Topics Found
   - **Adaptive Cap** (new)

2. **Extraction Pipeline Details** (expandable section):
   - Raw candidates extracted
   - After header filter (>10% removed)
   - After frequency filter (min 2 or 3%)
   - After similarity clustering (90% threshold)
   - After hierarchical merge
   - Final topics (ranked & capped)
   - **Reduction percentage**

3. **Subtopics viewer** (optional toggle):
   - Shows hierarchically merged subtopics
   - Example: "Oligopoly I: Cournot" → parent "Oligopoly"

4. **Updated topic display:**
   - Replaced "Confidence" with "Frequency" (occurrence count)
   - Added "Has Subtopics?" column
   - Backward compatible with old format

---

## Main Entry Point

**Function:** `extract_topic_candidates(pdf_files)` (line 475)

**Pipeline:**
1. Extract candidates from all PDFs
2. Filter repeated headers (> 10% of pages)
3. Filter by frequency (min 2 or 3% of pages)
4. Cluster similar topics (90% similarity)
5. Merge hierarchical topics
6. Rank and cap output (8-25 topics)

**Returns:**
- `final_topics`: List of 8-25 high-quality topics
- `stats`: Detailed statistics for UI display

---

## Test Results

**File:** `test_pdf_extractor.py`

### End-to-End Test (100-page lecture deck):

**Input:**
- 188 raw candidates (course headers, boilerplate, slide titles, section topics)

**Pipeline:**
1. After header filter: 88 (-53%)
2. After frequency filter: 16 (-91%)
3. After clustering: 16 (0%)
4. After hierarchical merge: 14 main topics, 3 subtopics (-87%)
5. **Final topics: 14 (-92.6% total reduction)**

**Final Output:**
```
1. Oligopoly [+3 subtopics] (freq: 9)
2. Supply and Demand (freq: 5)
3. Market Structures (freq: 5)
4. Monopoly (freq: 5)
5. Game Theory (freq: 5)
6. Market Equilibrium (freq: 4)
7. Elasticity (freq: 4)
8. Perfect Competition (freq: 4)
9. Nash Equilibrium (freq: 4)
10. Pricing Strategies (freq: 4)
11. Market Power (freq: 4)
12. Consumer Surplus (freq: 3)
13. Producer Surplus (freq: 3)
14. Dominant Strategies (freq: 3)
```

---

## Usage

### Basic Usage (unchanged):
```python
from pdf_extractor import extract_and_process_topics

pdf_files = [(pdf_bytes, filename), ...]
topics, stats = extract_and_process_topics(pdf_files)

print(f"Found {len(topics)} topics from {stats['total_pages']} pages")
print(f"Reduction: {stats['raw_candidates']} → {stats['final_topics']}")
```

### Run Tests:
```bash
# Run end-to-end demo
python test_pdf_extractor.py

# Run full test suite (requires pytest)
pytest test_pdf_extractor.py -v
```

---

## Files Changed

1. **pdf_extractor.py** (completely rewritten)
   - All extraction logic improved
   - New functions: `is_boilerplate`, `is_valid_candidate_line`, etc.
   - Main pipeline: `extract_topic_candidates`

2. **app.py** (UI updates only)
   - Lines 1646-1738: Extraction summary and topic display
   - Backward compatible with old data format

3. **test_pdf_extractor.py** (new file)
   - Unit tests for all requirements
   - End-to-end demonstration of 92.6% reduction

---

## Key Configuration Parameters

**All tunable in code:**

| Parameter | Location | Value | Effect |
|-----------|----------|-------|--------|
| Max font tolerance | `extract_page_candidates` | 95% | Only extract biggest titles |
| Header threshold | `filter_repeated_headers` | 10% of pages | Remove repeated headers |
| Min frequency | `filter_by_frequency` | max(2, 3% pages) | Section-level topics only |
| Similarity threshold | `cluster_similar_topics` | 90% | Merge similar topics |
| Output cap | `rank_and_cap_topics` | 8-25 adaptive | Limit final output |

---

## Expected Behavior

**Typical university lecture deck (50-100 pages):**
- **Old algorithm:** 50-200 topics (one per slide)
- **New algorithm:** 12-20 topics (section-level only)

**Small deck (20-30 pages):**
- **New algorithm:** 8-12 topics

**Large deck (150-200 pages):**
- **New algorithm:** 20-25 topics (capped at 25)

---

## Determinism & Stability

- **No randomness:** All operations are deterministic
- **Stable output:** Same PDF always produces same topics
- **No OCR:** Uses only PyMuPDF text + font sizes
- **Predictable:** Adaptive cap formula is consistent

---

## Dependencies

Required (no changes):
- `pymupdf` (fitz)
- `rapidfuzz`

Optional (for testing):
- `pytest`

---

## Migration Notes

**Backward Compatibility:**
- `extract_and_process_topics()` still works (legacy wrapper)
- UI handles both old format (confidence) and new format (occurrence_count)
- Existing Streamlit app will work without changes

**Breaking Changes:**
- Output topics now have `occurrence_count` instead of `confidence`
- `page_num` might be different (keeps first occurrence only after dedup)
- Stats dictionary has new fields (but old fields still present for compatibility)

---

## Future Improvements

Potential enhancements (not implemented):
1. User-configurable thresholds in UI
2. Export/save extraction settings
3. Topic preview before import
4. Multi-language boilerplate detection
5. Custom boilerplate patterns per user/course

---

## Summary

**Goal:** Reduce hundreds of topics to 8-25 high-quality topics ✅

**Achieved:**
- 92.6% reduction in test case
- Deterministic and stable output
- Works on typical university slide decks
- Adaptive to deck size
- Preserves hierarchical structure
- Shows detailed extraction statistics

**All requirements (A-F) implemented and tested.**
