# PDF Topic Extraction - Quick Reference

## What Changed?

**BEFORE:** 100+ topics extracted per deck (one per slide)
**AFTER:** 8-25 high-quality, course-level topics

---

## How It Works (5-Step Pipeline)

```
188 raw candidates
    ↓ [Filter headers >10%]
88 candidates
    ↓ [Filter by frequency: min 2 or 3% pages]
16 candidates
    ↓ [Cluster similar: 90% threshold]
16 candidates
    ↓ [Merge hierarchical: "Topic I/II" → "Topic"]
14 main topics
    ↓ [Rank & cap: 8-25 adaptive]
14 FINAL TOPICS (92.6% reduction!)
```

---

## What Gets Filtered Out?

### ❌ Removed (Requirement A):
- Course headers on every slide: "Economics 101 - Fall 2024"
- Boilerplate: "Agenda", "Questions?", "Thank You"
- University/professor names: "Frankfurt School", "Prof. Dr. Smith"
- One-off slide titles that appear only once

### ✅ Kept:
- Section markers appearing 2+ times
- Topics spanning 3%+ of pages
- Major concepts with high font sizes
- Frequently repeated section headings

---

## What Gets Merged?

### Similar Topics (Requirement C):
```
"Market Equilibrium" + "Market Equilibria" → "Market Equilibrium"
"Game Theory" + "Game Theories" → "Game Theory"
```

### Hierarchical Topics (Requirement E):
```
"Oligopoly I: Cournot" +
"Oligopoly II: Bertrand" +
"Oligopoly III: Stackelberg" → "Oligopoly" [+3 subtopics]
```

---

## Example Output

For a 100-page Economics lecture deck:

```
FINAL TOPICS (14):
1. Oligopoly [+3 subtopics] (appears on 9 pages)
2. Supply and Demand (appears on 5 pages)
3. Market Structures (appears on 5 pages)
4. Monopoly (appears on 5 pages)
5. Game Theory (appears on 5 pages)
6. Market Equilibrium (appears on 4 pages)
7. Elasticity (appears on 4 pages)
8. Perfect Competition (appears on 4 pages)
9. Nash Equilibrium (appears on 4 pages)
10. Pricing Strategies (appears on 4 pages)
11. Market Power (appears on 4 pages)
12. Consumer Surplus (appears on 3 pages)
13. Producer Surplus (appears on 3 pages)
14. Dominant Strategies (appears on 3 pages)
```

---

## UI Changes

### New Metrics:
- **Adaptive Cap:** Shows the calculated limit (8-25)
- **Reduction %:** Shows how much filtering happened

### New Expandable Section: "📊 Extraction Pipeline Details"
Shows candidates at each stage:
1. Raw candidates: 188
2. After header filter: 88
3. After frequency filter: 16
4. After clustering: 16
5. After hierarchical merge: 14
6. Final topics: 14
7. ✅ Reduced by 92.6%

### New Toggle: "Show Subtopics"
View hierarchically merged topics (e.g., "Oligopoly I/II/III")

### Updated Topic Table:
- **Old:** Confidence score
- **New:** Frequency (how many pages)
- **New:** Has Subtopics? column

---

## Run Tests

### Quick Demo:
```bash
python test_pdf_extractor.py
```

Output:
```
Raw candidates: 188
After header filter: 88
After frequency filter: 16
After clustering: 16
After hierarchical merge: 14 main topics, 3 subtopics
Final topics: 14

>>> Reduction: 188 -> 14 topics (92.6% reduction)
```

### Full Test Suite:
```bash
pip install pytest
pytest test_pdf_extractor.py -v
```

---

## Tuning Parameters (Advanced)

If you need to adjust the aggressiveness, edit these values in `pdf_extractor.py`:

| What to Change | Where | Current | Effect |
|----------------|-------|---------|--------|
| More/fewer topics | Line 470: `round(sqrt(total_pages) * 3)` | `* 3` | Increase multiplier for more topics |
| Min frequency | Line 277: `total_pages * 0.03` | `0.03` | Lower = more topics (more one-offs) |
| Header threshold | Line 251: `total_pages * 0.10` | `0.10` | Raise = keep more repeated items |
| Similarity | Line 516: `similarity_threshold=90.0` | `90.0` | Lower = merge more aggressively |
| Font tolerance | Line 181: `max_font * 0.95` | `0.95` | Lower = include smaller fonts |

**Recommendation:** Don't change unless you have specific issues. Current values work well for typical university lectures.

---

## Troubleshooting

### "Getting too few topics (< 8)"
**Cause:** PDF might have inconsistent formatting or very short deck
**Solution:**
1. Check if topics actually appear multiple times
2. Lower min frequency threshold (line 277)
3. Lower font tolerance (line 181)

### "Still getting too many topics (> 25)"
**Cause:** Should be capped at 25 automatically
**Check:**
1. Are you using the NEW version? Check `adaptive_cap` in stats
2. Check if hierarchical merge is working (subtopics shown?)

### "Important topics missing"
**Cause:** Topic might appear on too many pages (treated as header)
**Solution:**
1. Check "Extraction Pipeline Details" to see where it was filtered
2. Raise header threshold from 10% to 15% (line 251)

### "Similar topics not merging"
**Cause:** Similarity < 90%
**Solution:**
1. Lower similarity threshold to 85% (line 516)
2. Check if topics have very different wording

---

## Code Structure

```
pdf_extractor.py
├── normalize_text()          # Normalize for comparison
├── is_boilerplate()          # Check for generic text
├── is_valid_candidate_line() # Validate candidate
│
├── extract_page_candidates() # Extract from single page (MAX font only)
├── extract_all_candidates()  # Extract from all pages
│
├── filter_repeated_headers() # Remove > 10% occurrence
├── filter_by_frequency()     # Keep min 2 or 3% pages
├── cluster_similar_topics()  # Merge 90% similar
├── merge_hierarchical_topics() # Merge "Topic I/II" patterns
├── rank_and_cap_topics()     # Sort and limit to 8-25
│
└── extract_topic_candidates() # MAIN PIPELINE

test_pdf_extractor.py
├── TestBoilerplateDetection
├── TestCandidateValidation
├── TestRepeatedHeaderFilter
├── TestFrequencyFilter
├── TestSimilarityClustering
├── TestHierarchicalMerge
├── TestRankingAndCapping
└── TestEndToEndReduction    # 100-page demo
```

---

## Key Differences from Old Version

| Aspect | Old | New |
|--------|-----|-----|
| Font threshold | ≥ 70% of max | ≥ 95% of max |
| Header removal | ≥ 30% of pages | ≥ 10% of pages |
| Min frequency | None | ≥ max(2, 3% pages) |
| Similarity merge | 90% threshold | 90% + substring removal |
| Hierarchical merge | None | Detects I/II/III patterns |
| Output cap | None | Adaptive 8-25 |
| Boilerplate patterns | ~12 patterns | ~40 patterns |

---

## Expected Results by Deck Size

| Pages | Expected Topics | Cap Formula |
|-------|----------------|-------------|
| 10 | 8-9 | min(25, max(8, 9)) = 9 |
| 25 | 8-15 | min(25, max(8, 15)) = 15 |
| 50 | 12-21 | min(25, max(8, 21)) = 21 |
| 100 | 18-25 | min(25, max(8, 30)) = 25 |
| 200 | 20-25 | min(25, max(8, 42)) = 25 |

---

## Common Patterns Detected

### Hierarchical Patterns (auto-merged):
- "Topic I: ...", "Topic II: ..."
- "Module 1: ...", "Module 2: ..."
- "Part A: ...", "Part B: ..."
- "Lecture 1 - ...", "Lecture 2 - ..."

### Boilerplate Patterns (auto-removed):
- Course identifiers with years
- Professor/instructor names
- University names
- "Agenda", "Outline", "Overview"
- "Questions?", "Q&A"
- "Thank you", "The End"
- "References", "Bibliography"

---

## Tips for Best Results

1. **Use consistent slide formatting:** Topics should have largest font on page
2. **Repeat section markers:** Show topic name on multiple slides in section
3. **Avoid one-off titles:** Single-slide topics will be filtered out
4. **Use hierarchical numbering:** "Part I/II" will be merged smartly

---

## Performance

- **No OCR:** Fast, text-based extraction only
- **Deterministic:** Same input = same output
- **Memory efficient:** Processes PDFs in streaming mode
- **Typical speed:** < 2 seconds for 100-page deck

---

## Questions?

Check `IMPLEMENTATION_SUMMARY.md` for detailed technical documentation.

Run tests to see it in action:
```bash
python test_pdf_extractor.py
```
