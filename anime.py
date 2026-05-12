"""
Anime Library Tool
==================
This script allows users to search for anime titles using the Jikan API, 
extract key metadata, and display it as a JSON-based structure.
"""

import json
import argparse
from jikanpy import Jikan


def search_anime(query):
    """
    Searches the Jikan API for a list of anime matching the query.
    
    Args:
        query (str): The search term.
        
    Returns:
        list: A list of up to 5 matching anime records.
    """
    jikan = Jikan()
    search_results = jikan.search("anime", query, parameters={"limit": 5})
    return search_results["data"]


def fetch_anime_details(mal_id):
    """
    Retrieves refined metadata for a specific anime ID.
    
    Args:
        mal_id (int): The MyAnimeList ID of the anime.
        
    Returns:
        dict: A dictionary containing the 6 requested parameters.
    """
    jikan = Jikan()
    
    # Retrieve full anime details and community recommendations.
    details = jikan.anime(mal_id)["data"]
    recs_res = jikan.anime(mal_id, extension="recommendations")
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
    Executes the interactive search and display workflow.
    """
    parser = argparse.ArgumentParser(description="Anime Library Tool")
    parser.add_argument("title", nargs="?", help="Anime title to search")
    args = parser.parse_args()

    # Handle user input for the anime title.
    query = args.title if args.title else input("Enter the name of the anime: ")
    if not query:
        print("Error: No title provided.")
        return

    print(f"Searching for matches for '{query}'...")
    results = search_anime(query)
    
    if not results:
        print("No results found. Please try a different title.")
        return

    # Display the top 5 matches for user selection.
    print("\n--- Search Results ---")
    for i, anime in enumerate(results, start=1):
        title = anime["title"]
        year = anime.get("year") if anime.get("year") else "N/A"
        score = anime.get("score") if anime.get("score") else "N/A"
        print(f"[{i}] {title} ({year}) - Score: {score}")

    # Handle user selection.
    try:
        choice = int(input("\nPick a number (1-5) or 0 to cancel: "))
        if choice == 0:
            print("Operation cancelled.")
            return
        if not (1 <= choice <= len(results)):
            print("Invalid selection.")
            return
    except ValueError:
        print("Invalid input. Please enter a number.")
        return

    selected_anime = results[choice - 1]
    print(f"Fetching details for '{selected_anime['title']}'...")
    
    metadata = fetch_anime_details(selected_anime["mal_id"])
        
    # Print the result as a formatted JSON string.
    print("\n--- Result (JSON) ---")
    print(json.dumps(metadata, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()
