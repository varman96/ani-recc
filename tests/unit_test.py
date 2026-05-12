"""
Anime Library Unit Tests
========================
This script contains the unit test suite for anime.py. It uses mocking to 
simulate Jikan API responses and validates data mapping and edge cases.
"""

import unittest
from unittest.mock import MagicMock, patch
from anime import search_anime, fetch_anime_details


class TestAnimeMetadata(unittest.TestCase):
    """
    Unit tests for search and optimized metadata retrieval functions.
    """

    def setUp(self):
        """
        Sets up the mock data structures for API responses.
        """
        # Full record mimicking a search result entry.
        self.mock_selected_anime = {
            "mal_id": 1,
            "title": "Test Anime Full Title",
            "genres": [{"name": "Action"}, {"name": "Adventure"}],
            "themes": [{"name": "Sci-Fi"}],
            "score": 8.5,
            "rating": "PG-13 - Teens 13 or older",
            "year": 2024
        }
        
        self.mock_search_data = {
            "data": [self.mock_selected_anime]
        }
        
        self.mock_recommendations_data = {
            "data": [
                {"entry": {"title": "Rec 1"}},
                {"entry": {"title": "Rec 2"}},
                {"entry": {"title": "Rec 3"}},
                {"entry": {"title": "Rec 4"}},
                {"entry": {"title": "Rec 5"}}
            ]
        }

    @patch('anime.Jikan')
    def test_search_anime_success(self, MockJikan):
        """
        Verify that search_anime returns the correct list of matches.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        instance = MockJikan.return_value
        instance.search.return_value = self.mock_search_data

        results = search_anime("Test Query")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Test Anime Full Title")

    @patch('anime.Jikan')
    def test_fetch_details_mapping_success(self, MockJikan):
        """
        Verify that the 6 parameters are mapped correctly using only the recommendations call.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        instance = MockJikan.return_value
        instance.anime.return_value = self.mock_recommendations_data

        result = fetch_anime_details(self.mock_selected_anime)

        # Verify the 6-parameter mapping remains accurate using mixed data sources.
        self.assertEqual(result["Anime Name"], "Test Anime Full Title")
        self.assertEqual(result["Genres — content similarity"], ["Action", "Adventure"])
        self.assertEqual(result["Themes — more precise content similarity"], ["Sci-Fi"])
        self.assertEqual(result["Recommendations — community intuition"], ["Rec 1", "Rec 2", "Rec 3", "Rec 4", "Rec 5"])
        self.assertEqual(result["MAL Score — quality signal"], 8.5)
        self.assertEqual(result["Rating — tone/audience"], "PG-13 - Teens 13 or older")

    @patch('anime.Jikan')
    def test_fetch_details_api_error(self, MockJikan):
        """
        Test how the script handles API exceptions during the recommendations call.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        instance = MockJikan.return_value
        instance.anime.side_effect = Exception("Recommendations Failed")

        with self.assertRaises(Exception):
            fetch_anime_details(self.mock_selected_anime)


if __name__ == '__main__':
    unittest.main()
