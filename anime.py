"""
Anime Library Tool
==================
This script allows users to search for anime titles using the Jikan API, 
extract key metadata, and append the results to a JSON-based library.
"""

import json
import os
import argparse
from jikanpy import Jikan


def fetch_anime_metadata(query):
    """
    Searches the Jikan API for an anime and retrieves refined metadata.
    
    Args:
        query (str): The search term provided by the user.
        
    Returns:
        dict: A dictionary containing the 6 requested parameters.
    """
    jikan = Jikan()
    
    # Search for the best match using the Jikan API.
    search_results = jikan.search("anime", query, parameters={"limit": 1})
    if not search_results["data"]:
        return None
        
    anime_id = search_results["data"][0]["mal_id"]
    
    # Retrieve full anime details and community recommendations.
    details = jikan.anime(anime_id)["data"]
    recs_res = jikan.anime(anime_id, extension="recommendations")
    recommendations = [r["entry"]["title"] for r in recs_res["data"][:5]]
    
    # Construct the final data structure.
    return {
        "Anime Name": details["title"],
        "Genres — content similarity": [g["name"] for g in details["genres"]],
        "Themes — more precise content similarity": 
            [t["name"] for t in details["themes"]],
        "Recommendations — community intuition": recommendations,
        "MAL Score — quality signal": details["score"],
        "Rating — tone/audience": details["rating"]
    }


def main():
    """
    Executes the primary workflow: input, search, and display as JSON.
    """
    parser = argparse.ArgumentParser(description="Anime Library Tool")
    parser.add_argument("title", nargs="?", 
                        help="Anime title to search")
    args = parser.parse_args()

    # Handle user input for the anime title.
    query = args.title if args.title else input("Enter the name of the anime: ")
    if not query:
        print("Error: No title provided.")
        return

    print(f"Searching for '{query}'...")
    metadata = fetch_anime_metadata(query)
    
    if not metadata:
        print("No results found. Please try a different title.")
        return
        
    # Print the result as a formatted JSON string.
    print("\n--- Result (JSON) ---")
    print(json.dumps(metadata, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()
