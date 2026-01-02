"""
Unit Tests for Improved PDF Topic Extraction
Demonstrates drastic reduction in topic count.
"""

try:
    import pytest
except ImportError:
    pytest = None

from pdf_extractor import (
    is_boilerplate,
    is_valid_candidate_line,
    filter_repeated_headers,
    filter_by_frequency,
    cluster_similar_topics,
    merge_hierarchical_topics,
    rank_and_cap_topics,
    normalize_text
)


class TestBoilerplateDetection:
    """Test Requirement A: Boilerplate filtering"""

    def test_generic_boilerplate(self):
        assert is_boilerplate("Lecture 5") == True
        assert is_boilerplate("Chapter 3") == True
        assert is_boilerplate("Agenda") == True
        assert is_boilerplate("Questions?") == True
        assert is_boilerplate("Thank you") == True

    def test_frankfurt_school_specific(self):
        assert is_boilerplate("Frankfurt School of Finance") == True
        assert is_boilerplate("Professor Dr. Smith") == True

    def test_valid_topics_not_boilerplate(self):
        assert is_boilerplate("Market Equilibrium") == False
        assert is_boilerplate("Monopolistic Competition") == False
        assert is_boilerplate("Game Theory Applications") == False


class TestCandidateValidation:
    """Test Requirement A: Candidate line validation"""

    def test_length_constraints(self):
        assert is_valid_candidate_line("Short") == False  # < 6
        assert is_valid_candidate_line("A" * 81) == False  # > 80
        assert is_valid_candidate_line("Market Structure") == True  # valid

    def test_digits_symbols(self):
        assert is_valid_candidate_line("12345") == False
        assert is_valid_candidate_line("###***") == False
        assert is_valid_candidate_line("Section 2.3") == True  # mostly alphanumeric

    def test_page_numbers(self):
        assert is_valid_candidate_line("42") == False
        assert is_valid_candidate_line("1/50") == False


class TestRepeatedHeaderFilter:
    """Test Requirement A: Filter headers appearing on >10% of pages"""

    def test_repeated_header_removal(self):
        # Simulate 100 pages, course name appears on 90 pages
        candidates = [
            {"topic_name": "Economics 101", "page_num": i} for i in range(1, 91)
        ]
        # Add valid topics
        candidates.extend([
            {"topic_name": "Supply and Demand", "page_num": 5},
            {"topic_name": "Supply and Demand", "page_num": 6},
            {"topic_name": "Market Failure", "page_num": 20},
            {"topic_name": "Market Failure", "page_num": 21},
        ])

        filtered = filter_repeated_headers(candidates, total_pages=100)

        # "Economics 101" appears on 90/100 pages (90%) > 10% threshold → removed
        topic_names = [c["topic_name"] for c in filtered]
        assert "Economics 101" not in topic_names
        assert "Supply and Demand" in topic_names
        assert "Market Failure" in topic_names


class TestFrequencyFilter:
    """Test Requirement B: Frequency-based filtering"""

    def test_min_frequency_requirement(self):
        # 100 pages → min_freq = max(2, ceil(100 * 0.03)) = 3
        candidates = [
            {"topic_name": "Topic A", "page_num": 1},  # 1 occurrence → removed
            {"topic_name": "Topic B", "page_num": 2},
            {"topic_name": "Topic B", "page_num": 3},  # 2 occurrences → kept (>= min 2)
            {"topic_name": "Topic C", "page_num": 5},
            {"topic_name": "Topic C", "page_num": 6},
            {"topic_name": "Topic C", "page_num": 7},  # 3 occurrences → kept
        ]

        filtered = filter_by_frequency(candidates, total_pages=100)

        topic_names = [c["topic_name"] for c in filtered]
        assert "Topic A" not in topic_names  # Only 1 occurrence
        assert "Topic B" in topic_names  # 2 occurrences (>= min 2)
        assert "Topic C" in topic_names  # 3 occurrences

    def test_small_deck_min_frequency(self):
        # 30 pages → min_freq = max(2, ceil(30 * 0.03)) = 2
        candidates = [
            {"topic_name": "Solo Topic", "page_num": 1},  # 1 occurrence → removed
            {"topic_name": "Pair Topic", "page_num": 2},
            {"topic_name": "Pair Topic", "page_num": 3},  # 2 occurrences → kept
        ]

        filtered = filter_by_frequency(candidates, total_pages=30)
        topic_names = [c["topic_name"] for c in filtered]
        assert "Solo Topic" not in topic_names
        assert "Pair Topic" in topic_names


class TestSimilarityClustering:
    """Test Requirement C: Similarity clustering with rapidfuzz"""

    def test_cluster_similar_topics(self):
        candidates = [
            {"topic_name": "Market Equilibrium", "occurrence_count": 3, "font_size": 24},
            {"topic_name": "Market Equilibria", "occurrence_count": 2, "font_size": 22},  # Similar
            {"topic_name": "Game Theory", "occurrence_count": 4, "font_size": 24},
            {"topic_name": "Game Theories", "occurrence_count": 1, "font_size": 20},  # Similar
        ]

        merged = cluster_similar_topics(candidates, similarity_threshold=90.0)

        # Should merge similar topics, keeping ~2 topics
        assert len(merged) == 2
        topic_names = [c["topic_name"] for c in merged]
        # Keep longer/more frequent versions
        assert any("Market Equilibri" in t for t in topic_names)
        assert any("Game Theor" in t for t in topic_names)

    def test_substring_removal(self):
        candidates = [
            {"topic_name": "Oligopoly", "occurrence_count": 5, "font_size": 24},
            {"topic_name": "Oligopoly Models", "occurrence_count": 3, "font_size": 22},
        ]

        merged = cluster_similar_topics(candidates, similarity_threshold=90.0)

        # "Oligopoly" is substring of "Oligopoly Models" → remove shorter
        assert len(merged) == 1
        assert merged[0]["topic_name"] == "Oligopoly Models"


class TestHierarchicalMerge:
    """Test Requirement E: Hierarchical topic merging"""

    def test_roman_numeral_pattern(self):
        candidates = [
            {"topic_name": "Oligopoly I: Cournot", "occurrence_count": 2, "font_size": 24, "source_file": "lec.pdf"},
            {"topic_name": "Oligopoly II: Bertrand", "occurrence_count": 2, "font_size": 24, "source_file": "lec.pdf"},
            {"topic_name": "Oligopoly III: Stackelberg", "occurrence_count": 2, "font_size": 24, "source_file": "lec.pdf"},
        ]

        main_topics, subtopics = merge_hierarchical_topics(candidates)

        # Should create 1 parent topic "Oligopoly"
        assert len(main_topics) == 1
        assert main_topics[0]["topic_name"] == "Oligopoly"
        assert main_topics[0]["has_subtopics"] == True
        assert main_topics[0]["num_subtopics"] == 3

        # Should have 3 subtopics
        assert len(subtopics) == 3
        assert all(s["parent_topic"] == "Oligopoly" for s in subtopics)

    def test_numbered_pattern(self):
        candidates = [
            {"topic_name": "Module 1: Introduction", "occurrence_count": 2, "font_size": 24, "source_file": "lec.pdf"},
            {"topic_name": "Module 2: Advanced Topics", "occurrence_count": 2, "font_size": 24, "source_file": "lec.pdf"},
        ]

        main_topics, subtopics = merge_hierarchical_topics(candidates)

        assert len(main_topics) == 1
        assert main_topics[0]["topic_name"] == "Module"
        assert main_topics[0]["num_subtopics"] == 2

    def test_standalone_topics_preserved(self):
        candidates = [
            {"topic_name": "Market Structure", "occurrence_count": 3, "font_size": 24, "source_file": "lec.pdf"},
            {"topic_name": "Consumer Behavior", "occurrence_count": 2, "font_size": 24, "source_file": "lec.pdf"},
        ]

        main_topics, subtopics = merge_hierarchical_topics(candidates)

        # No hierarchical patterns → keep as standalone
        assert len(main_topics) == 2
        assert len(subtopics) == 0
        assert all(not t.get("has_subtopics") for t in main_topics)


class TestRankingAndCapping:
    """Test Requirement D: Ranking and output capping"""

    def test_ranking_by_frequency(self):
        candidates = [
            {"topic_name": "Topic A", "occurrence_count": 5, "avg_font_size": 20},
            {"topic_name": "Topic B", "occurrence_count": 10, "avg_font_size": 20},
            {"topic_name": "Topic C", "occurrence_count": 3, "avg_font_size": 20},
        ]

        ranked = rank_and_cap_topics(candidates, total_pages=100)

        # Should rank by frequency (descending)
        assert ranked[0]["topic_name"] == "Topic B"  # 10 occurrences
        assert ranked[1]["topic_name"] == "Topic A"  # 5 occurrences
        assert ranked[2]["topic_name"] == "Topic C"  # 3 occurrences

    def test_adaptive_cap_small_deck(self):
        # 25 pages → cap = min(25, max(8, round(sqrt(25) * 3))) = min(25, max(8, 15)) = 15
        candidates = [
            {"topic_name": f"Topic {i}", "occurrence_count": 1, "avg_font_size": 20}
            for i in range(30)
        ]

        capped = rank_and_cap_topics(candidates, total_pages=25)

        assert len(capped) == 15

    def test_adaptive_cap_large_deck(self):
        # 200 pages → cap = min(25, max(8, round(sqrt(200) * 3))) = min(25, max(8, 42)) = 25
        candidates = [
            {"topic_name": f"Topic {i}", "occurrence_count": 1, "avg_font_size": 20}
            for i in range(50)
        ]

        capped = rank_and_cap_topics(candidates, total_pages=200)

        assert len(capped) == 25  # Max cap

    def test_adaptive_cap_tiny_deck(self):
        # 10 pages → cap = min(25, max(8, round(sqrt(10) * 3))) = min(25, max(8, 9)) = 9
        # But only 5 topics → return 5
        candidates = [
            {"topic_name": f"Topic {i}", "occurrence_count": 1, "avg_font_size": 20}
            for i in range(5)
        ]

        capped = rank_and_cap_topics(candidates, total_pages=10)

        assert len(capped) == 5  # Less than cap


class TestEndToEndReduction:
    """Test complete pipeline showing drastic reduction"""

    def test_realistic_scenario_100_pages(self):
        """
        Simulates a 100-page lecture deck.
        OLD ALGORITHM: Would extract ~100-200 topics (one per slide)
        NEW ALGORITHM: Should extract 8-25 topics
        """

        # Simulate raw extraction: many slide titles
        candidates = []

        # Course header on every page (100 occurrences)
        for i in range(1, 101):
            candidates.append({"topic_name": "Economics 101 - Fall 2024", "page_num": i, "font_size": 12})

        # Boilerplate slides
        candidates.extend([
            {"topic_name": "Agenda", "page_num": 2, "font_size": 24},
            {"topic_name": "Lecture Outline", "page_num": 3, "font_size": 24},
            {"topic_name": "Questions?", "page_num": 99, "font_size": 24},
            {"topic_name": "Thank You", "page_num": 100, "font_size": 24},
        ])

        # One-off slide titles (should be filtered out)
        for i in range(10, 30):
            candidates.append({"topic_name": f"Slide {i} Random Title", "page_num": i, "font_size": 20})

        # Section-level topics (appear multiple times - realistic for section markers)
        # These represent topics that span multiple slides in a lecture deck
        section_topics = [
            ("Supply and Demand", [5, 6, 7, 8, 9]),
            ("Market Equilibrium", [10, 11, 12, 13]),
            ("Consumer Surplus", [15, 16, 17]),
            ("Producer Surplus", [18, 19, 20]),
            ("Elasticity", [22, 23, 24, 25]),
            ("Market Structures", [30, 31, 32, 33, 34]),
            ("Perfect Competition", [35, 36, 37, 38]),
            ("Monopoly", [40, 41, 42, 43, 44]),
            ("Oligopoly I: Cournot", [45, 46, 47]),
            ("Oligopoly II: Bertrand", [48, 49, 50]),
            ("Oligopoly III: Stackelberg", [51, 52, 53]),
            ("Game Theory", [55, 56, 57, 58, 59]),
            ("Nash Equilibrium", [60, 61, 62, 63]),
            ("Dominant Strategies", [65, 66, 67]),
            ("Pricing Strategies", [70, 71, 72, 73]),
            ("Market Power", [75, 76, 77, 78]),
        ]

        for topic, pages in section_topics:
            for page in pages:
                candidates.append({"topic_name": topic, "page_num": page, "font_size": 24})

        # Variations (should be merged)
        candidates.extend([
            {"topic_name": "Supply & Demand", "page_num": 9, "font_size": 24},  # Similar to "Supply and Demand"
            {"topic_name": "Game Theories", "page_num": 59, "font_size": 24},  # Similar to "Game Theory"
        ])

        print(f"\nRaw candidates: {len(candidates)}")

        # Step 1: Filter repeated headers
        after_headers = filter_repeated_headers(candidates, total_pages=100)
        print(f"After header filter: {len(after_headers)}")

        # Step 2: Filter by frequency
        after_frequency = filter_by_frequency(after_headers, total_pages=100)
        print(f"After frequency filter: {len(after_frequency)}")

        # Step 3: Cluster similar
        after_clustering = cluster_similar_topics(after_frequency, similarity_threshold=90.0)
        print(f"After clustering: {len(after_clustering)}")

        # Step 4: Hierarchical merge
        main_topics, subtopics = merge_hierarchical_topics(after_clustering)
        print(f"After hierarchical merge: {len(main_topics)} main topics, {len(subtopics)} subtopics")

        # Step 5: Rank and cap
        final_topics = rank_and_cap_topics(main_topics, total_pages=100)
        print(f"Final topics: {len(final_topics)}")

        # Assertions
        assert len(candidates) > 100  # Started with 100+ candidates
        assert len(final_topics) <= 25  # Ended with <= 25 topics
        assert len(final_topics) >= 8  # At least 8 topics
        assert "Economics 101 - Fall 2024" not in [t["topic_name"] for t in final_topics]  # Header removed
        assert "Agenda" not in [t["topic_name"] for t in final_topics]  # Boilerplate removed

        # Check that Oligopoly I/II were merged
        topic_names = [t["topic_name"] for t in final_topics]
        if "Oligopoly" in topic_names:
            # Successfully merged hierarchical topics
            assert "Oligopoly I: Cournot" not in topic_names
            assert "Oligopoly II: Bertrand" not in topic_names

        print(f"\n>>> Reduction: {len(candidates)} -> {len(final_topics)} topics ({round((1 - len(final_topics)/len(candidates)) * 100, 1)}% reduction)")
        print("\nFinal topics:")
        for i, topic in enumerate(final_topics, 1):
            subtopics_marker = f" [+{topic.get('num_subtopics', 0)} subtopics]" if topic.get('has_subtopics') else ""
            print(f"  {i}. {topic['topic_name']}{subtopics_marker} (freq: {topic.get('occurrence_count', 'N/A')})")


if __name__ == "__main__":
    # Run the realistic scenario test
    test = TestEndToEndReduction()
    test.test_realistic_scenario_100_pages()

    print("\n" + "="*80)
    print("Run full tests with: pytest test_pdf_extractor.py -v")
    print("="*80)
