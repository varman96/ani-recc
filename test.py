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


def update_anime_library(anime_data, filename="anime_library.json"):
    """
    Appends a new anime record to the specified JSON library file.
    
    Args:
        anime_data (dict): The dictionary containing anime metadata.
        filename (str): The path to the JSON library file.
    """
    library = []
    
    # Load the existing library if the file is present.
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as file_handle:
            try:
                library = json.load(file_handle)
            except json.JSONDecodeError:
                library = []
    
    # Append the new record and save to disk.
    library.append(anime_data)
    with open(filename, "w", encoding="utf-8") as file_handle:
        json.dump(library, file_handle, indent=4, ensure_ascii=False)
    
    print(f"\n[Success] Added to {filename}!")


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
    Executes the primary workflow: input, search, display, and storage.
    """
    parser = argparse.ArgumentParser(description="Anime Library Tool")
    parser.add_argument("--refresh", action="store_true", 
                        help="Clear the library before saving")
    parser.add_argument("title", nargs="?", 
                        help="Anime title to search")
    args = parser.parse_args()

    # Clear the library if the force refresh flag is set.
    if args.refresh and os.path.exists("anime_library.json"):
        os.remove("anime_library.json")
        print("[Info] Library cleared (Force Refresh enabled).")

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
        
    # Display the results with Unicode error handling for the terminal.
    print("\n--- Found Match ---")
    for key, value in metadata.items():
        try:
            display_val = ", ".join(value) if isinstance(value, list) else value
            print(f"{key}: {display_val if display_val else 'None'}")
        except UnicodeEncodeError:
            print(f"{key}: [Encoding error: Simplified view in terminal]")
            
    update_anime_library(metadata)


if __name__ == "__main__":
    main()
