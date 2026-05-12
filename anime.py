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


def fetch_anime_details(selected_anime):
    """
    Retrieves recommendations and combines them with existing metadata.
    
    Args:
        selected_anime (dict): The anime record retrieved from the search results.
        
    Returns:
        dict: A dictionary containing the 6 requested parameters.
    """
    jikan = Jikan()
    mal_id = selected_anime["mal_id"]
    
    # Only one additional call is needed for community recommendations.
    recs_res = jikan.anime(mal_id, extension="recommendations")
    recommendations = [r["entry"]["title"] for r in recs_res["data"][:5]]
    
    # Reuse the metadata already present in the search result to save an API call.
    data = {
        "Anime Name": selected_anime["title"],
        "Genres": [g["name"] for g in selected_anime.get("genres", [])],
        "Recommendations": recommendations,
        "MAL Score": selected_anime.get("score"),
        "Audience": selected_anime.get("rating")
    }
    
    # Only include themes if the list is not empty.
    themes = [t["name"] for t in selected_anime.get("themes", [])]
    if themes:
        data["Themes"] = themes
        
    return data


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
        print(f"[{i}] {anime['title']}")

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
    print(f"Getting info for '{selected_anime['title']}'...")
    
    # Process the selected anime data.
    metadata = fetch_anime_details(selected_anime)
        
    # Print the result as a formatted JSON string.
    print("\n--- Result (JSON) ---")
    print(json.dumps(metadata, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()
