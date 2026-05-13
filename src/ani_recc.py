"""
Anime Library Tool
==================
This script allows users to search for anime titles using the Jikan API, 
extract key metadata, and display it as a JSON-based structure.
"""

import json
import argparse
import requests
import knn
import re


def get_seed_name(title):
    """
    Strips away sequel markers to find the primary 'Seed Name' of a franchise.
    """
    # 1. Always prioritize the colon as a franchise/subtitle marker.
    if ":" in title:
        title = title.split(":")[0]
        
    # 2. Refined patterns for other sequel markers and meta-info.
    patterns = [
        r"\s*\(.*\)$",      # Meta info in parentheses (e.g., "(Shinsaku Anime)", "(TV)")
        r"\s+(?:\d+(?:st|nd|rd|th)|Season|Part|Movie)\s+(?:Season|Part|Movie|\d+)",
        r"\s+\d+(?:st|nd|rd|th)\s+Season",
        r"\s+Season\s+\d+",
        r"\s+Part\s+\d+",
        r"\s+Movie\s+\d+",
        r"\s+[IVXLCDM]+$", 
        r"\s+\d+$"          
    ]
    seed = title
    for p in patterns:
        seed = re.split(p, seed, flags=re.IGNORECASE)[0]
    return seed.strip()


def search_anime(query):
    """
    Searches the Jikan API and aggregates results by franchise seed name.
    
    Args:
        query (str): The search term.
        
    Returns:
        list: A list of unique franchise records.
    """
    base_url = "https://api.jikan.moe/v4/anime"
    params = {"q": query, "limit": 25}
    response = requests.get(base_url, params=params)
    response.raise_for_status()
    search_results = response.json()
    
    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]
    
    franchises = {} # seed_name_lower -> first_anime_object
    
    for anime in search_results["data"]:
        # 1. Type, Genre & Rating Filtering
        if anime.get("type") not in allowed_types:
            continue
        if any(g["name"] in forbidden_genres for g in anime.get("genres", [])):
            continue
        if not anime.get("score") or anime.get("score") == 0:
            continue
            
        # 2. Grouping by Seed Name
        seed = get_seed_name(anime["title"])
        seed_lower = seed.lower()
        
        if seed_lower not in franchises:
            # Overwrite the title to the seed name for the display list
            anime["title"] = seed
            franchises[seed_lower] = anime
            
    return list(franchises.values())[:5]


def fetch_anime_details(selected_anime):
    """
    Retrieves metadata for the selected anime, including community recommendations.
    
    Args:
        selected_anime (dict): The anime record retrieved from the search results.
        
    Returns:
        dict: A dictionary containing the requested parameters.
    """
    mal_id = selected_anime["mal_id"]
    base_url = f"https://api.jikan.moe/v4/anime/{mal_id}/recommendations"
    response = requests.get(base_url)
    response.raise_for_status()
    recs_res = response.json()
    
    # Clean the recommendation titles and take ONLY the top 3
    recommendations = [get_seed_name(r["entry"]["title"]) for r in recs_res["data"][:3]]
    
    # Extract only the requested metadata to save on API calls and keep the JSON clean.
    data = {
        "Anime Name": selected_anime["title"],
        "Genres": [g["name"] for g in selected_anime.get("genres", [])],
        "Demographics": [d["name"] for d in selected_anime.get("demographics", [])],
        "Themes": [t["name"] for t in selected_anime.get("themes", [])],
        "Recommendations": recommendations,
        "Rank": selected_anime.get("rank"),
        "Popularity": selected_anime.get("popularity"),
        "Members": selected_anime.get("members")
    }
    
    return data


def get_top_candidates_by_genre(genre_ids, selected_anime, seen_franchises, limit=25):
    """
    Finds and aggregates top-ranked animes by genre, merging sequels and excluding seen history.
    """
    base_url = "https://api.jikan.moe/v4/anime"
    if not genre_ids:
        return []

    primary_genre_id = genre_ids[0]
    params = {
        "genres": str(primary_genre_id),
        "order_by": "score",
        "sort": "desc",
        "min_score": 1,
        "limit": 25
    }
    response = requests.get(base_url, params=params)
    response.raise_for_status()
    search_results = response.json()

    source_genre_ids = set(genre_ids)
    source_title_root = get_seed_name(selected_anime["title"]).lower()
    
    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]
    
    franchises = {} # clean_name_lower -> { "display_name": str, "versions": [] }

    for anime in search_results["data"]:
        title = anime["title"]
        clean_name = get_seed_name(title)
        clean_lower = clean_name.lower()
        
        # 1. Skip the reference anime, its sequels, and anything already seen in this chain.
        if clean_lower == source_title_root or clean_lower in seen_franchises:
            continue
            
        # 2. Type, Genre & Rating Filtering.
        if anime.get("type") not in allowed_types:
            continue
        if not anime.get("score") or anime.get("score") == 0:
            continue
            
        anime_genres = anime.get("genres", [])
        if any(g["name"] in forbidden_genres for g in anime_genres):
            continue
            
        # 3. Dynamic Genre Matching.
        anime_genre_ids = {g["mal_id"] for g in anime_genres}
        matches = len(source_genre_ids & anime_genre_ids)
        num_source = len(source_genre_ids)
        
        # Rule: 2 matches for 3+ genres; 1 match for 1-2 genres.
        required = 2 if num_source >= 3 else 1
        if matches < required:
            continue
 
        # 4. Aggregation into "Sub-Folders".
        if clean_lower not in franchises:
            franchises[clean_lower] = {
                "Clean Name": clean_name,
                "Versions": []
            }
        
        # Store this specific version's metadata
        franchises[clean_lower]["Versions"].append({
            "Title": title,
            "Genres": {g["name"] for g in anime_genres},
            "Demographics": {d["name"] for d in anime.get("demographics", [])},
            "Themes": {t["name"] for t in anime.get("themes", [])},
            "Score": anime.get("score") or 0,
            "Rank": anime.get("rank") or 999999,
            "Popularity": anime.get("popularity") or 999999,
            "Members": anime.get("members") or 0
        })

    # Convert Aggregated Franchises into flattened objects for KNN.
    final_candidates = []
    for f in franchises.values():
        versions = f["Versions"]
        
        # Merge logic for the "Sub-Folder"
        all_genres = set()
        all_demos = set()
        all_themes = set()
        scores = []
        best_rank = 999999
        best_pop = 999999
        total_members = 0
        
        for v in versions:
            all_genres.update(v["Genres"])
            all_demos.update(v["Demographics"])
            all_themes.update(v["Themes"])
            scores.append(v["Score"])
            best_rank = min(best_rank, v["Rank"])
            best_pop = min(best_pop, v["Popularity"])
            total_members += v["Members"]

        final_candidates.append({
            "Anime Name": f["Clean Name"],
            "Version Count": len(versions),
            "Genres": list(all_genres),
            "Demographics": list(all_demos),
            "Themes": list(all_themes),
            "Rank": best_rank,
            "Popularity": best_pop,
            "Members": total_members,
            "MAL Score": max(scores) if scores else 0
        })
        if len(final_candidates) >= limit:
            break
            
    return final_candidates


def main():
    """
    Executes the interactive search and display workflow.
    """
    parser = argparse.ArgumentParser(description="Anime Library Tool")
    parser.add_argument("title", nargs="?", help="Anime title to search")
    args = parser.parse_args()

    # History and depth tracking for the session
    history = set()
    chain_depth = 0
    current_query = args.title

    while True:
        if not current_query:
            current_query = input("\nEnter the name of the anime (or 'exit' to quit): ")
            if current_query.lower() == 'exit':
                break
            history = set() # Reset history on fresh search
            chain_depth = 0
        
        print(f"\nSearching for matches for '{current_query}'...")
        results = search_anime(current_query)
        
        if not results:
            print("No results found. Please try a different title.")
            current_query = None
            continue

        # If we are in a "Continue" chain, we auto-select the first match if it matches perfectly
        if chain_depth > 0 and results[0]['title'].lower() == current_query.lower():
            selected_anime = results[0]
        else:
            # Display the top 5 matches for user selection.
            print("\n--- Search Results ---")
            for i, anime in enumerate(results, start=1):
                print(f"[{i}] {anime['title']}")

            # Handle user selection.
            try:
                choice_raw = input("\nPick a number (1-5) or 0 to cancel: ")
                if not choice_raw.strip():
                    current_query = None
                    continue
                choice = int(choice_raw)
                if choice == 0:
                    print("Operation cancelled.")
                    current_query = None
                    continue
                selected_anime = results[choice - 1]
            except (ValueError, IndexError):
                print("Invalid selection.")
                current_query = None
                continue

        # Add to history
        history.add(get_seed_name(selected_anime['title']).lower())
        
        print(f"\n--- Reference Anime: {selected_anime['title']} ---")
        
        # 1. Generate and print JSON for the reference anime only.
        metadata = fetch_anime_details(selected_anime)
        print(json.dumps(metadata, indent=4, ensure_ascii=True))
        
        # 2. Extract genres and find top 25 candidates.
        print(f"\nFinding top 25 candidates with matching genres...")
        genre_ids = [g["mal_id"] for g in selected_anime.get("genres", [])]
        candidates = get_top_candidates_by_genre(genre_ids, selected_anime, history)
        
        if not candidates:
            print("No new candidates found in this chain! Try a fresh search.")
            current_query = None
            continue

        # 3. Final Output in the terminal.
        print("\n--- Candidate Pool (Aggregated Franchises) ---")
        for i, anime in enumerate(candidates, start=1):
            version_text = f"({anime['Version Count']} versions)"
            score_display = f"(Avg Score: {round(anime['MAL Score'], 2)})"
            print(f"[{i}] {anime['Anime Name']} {version_text} {score_display}")
                
        # 4. Generate KNN Vectors and get the top match
        top_match_name = knn.process_vectors(metadata, candidates, chain_depth)

        # 5. Refresh / Exit / Continue Prompt
        prompt = "\n[R] Refresh (New Search) | [X] Exit"
        if top_match_name:
            prompt += f" | [C] Continue with '{top_match_name}'"
        
        action = input(f"{prompt}: ").lower()
        
        if action == 'x':
            break
        elif action == 'c' and top_match_name:
            current_query = top_match_name
            chain_depth += 1
        else:
            current_query = None # Clear query to prompt for next title

if __name__ == "__main__":
    main()
