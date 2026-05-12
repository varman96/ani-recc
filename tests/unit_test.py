"""
Anime Library Unit Tests
========================
This script contains the unit test suite for anime.py. It uses mocking to 
simulate Jikan API responses and validates data mapping and edge cases.
"""

import unittest
from unittest.mock import MagicMock, patch
from anime import fetch_anime_metadata


class TestAnimeMetadata(unittest.TestCase):
    """
    Unit tests for the fetch_anime_metadata function.
    """

    def setUp(self):
        """
        Sets up the mock data structures for API responses.
        """
        # Sample mock data mimicking Jikan API v4 structure.
        self.mock_search_data = {
            "data": [{"mal_id": 1, "title": "Test Anime"}]
        }
        
        self.mock_details_data = {
            "data": {
                "title": "Test Anime Full Title",
                "genres": [{"name": "Action"}, {"name": "Adventure"}],
                "themes": [{"name": "Sci-Fi"}],
                "score": 8.5,
                "rating": "PG-13 - Teens 13 or older"
            }
        }
        
        self.mock_recommendations_data = {
            "data": [
                {"entry": {"title": "Rec 1"}},
                {"entry": {"title": "Rec 2"}},
                {"entry": {"title": "Rec 3"}},
                {"entry": {"title": "Rec 4"}},
                {"entry": {"title": "Rec 5"}},
                {"entry": {"title": "Rec 6"}} 
            ]
        }

    @patch('anime.Jikan')
    def test_fetch_metadata_mapping_success(self, MockJikan):
        """
        Verify that specific keys are correctly mapped to each of the 6 parameters.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        # Configure mock instance methods.
        instance = MockJikan.return_value
        instance.search.return_value = self.mock_search_data
        instance.anime.side_effect = [
            self.mock_details_data,           
            self.mock_recommendations_data    
        ]

        result = fetch_anime_metadata("Test Query")

        # Verify the 6-parameter mapping remains accurate.
        self.assertIsNotNone(result)
        self.assertEqual(result["Anime Name"], "Test Anime Full Title")
        self.assertEqual(result["Genres — content similarity"], ["Action", "Adventure"])
        self.assertEqual(result["Themes — more precise content similarity"], ["Sci-Fi"])
        self.assertEqual(result["Recommendations — community intuition"], ["Rec 1", "Rec 2", "Rec 3", "Rec 4", "Rec 5"])
        self.assertEqual(result["MAL Score — quality signal"], 8.5)
        self.assertEqual(result["Rating — tone/audience"], "PG-13 - Teens 13 or older")

    @patch('anime.Jikan')
    def test_fetch_metadata_missing_data(self, MockJikan):
        """
        Validate behavior when no search results are found.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        instance = MockJikan.return_value
        instance.search.return_value = {"data": []}

        result = fetch_anime_metadata("Nonexistent Anime")
        
        # Verify the script returns None for empty search results.
        self.assertIsNone(result)

    @patch('anime.Jikan')
    def test_fetch_metadata_malformed_fields(self, MockJikan):
        """
        Validate behavior when optional data fields are empty.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        instance = MockJikan.return_value
        instance.search.return_value = self.mock_search_data
        
        # Construct details with empty list values for genres and themes.
        malformed_details = self.mock_details_data.copy()
        malformed_details["data"]["genres"] = []
        malformed_details["data"]["themes"] = []
        
        instance.anime.side_effect = [
            malformed_details,
            {"data": []} 
        ]

        result = fetch_anime_metadata("Test Query")

        # Verify mapping handles empty lists gracefully.
        self.assertEqual(result["Genres — content similarity"], [])
        self.assertEqual(result["Themes — more precise content similarity"], [])
        self.assertEqual(result["Recommendations — community intuition"], [])

    @patch('anime.Jikan')
    def test_fetch_metadata_api_error(self, MockJikan):
        """
        Test how the script handles API exceptions.
        
        Args:
            MockJikan: The mocked Jikan API class.
        """
        instance = MockJikan.return_value
        instance.search.side_effect = Exception("API Connection Failed")

        # Verify that unexpected API errors are propagated or caught.
        with self.assertRaises(Exception) as context:
            fetch_anime_metadata("Test Query")
        
        self.assertTrue("API Connection Failed" in str(context.exception))


if __name__ == '__main__':
    unittest.main()
