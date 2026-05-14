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


def is_same_franchise(title1, title2, threshold=0.5):
    """
    Checks if two titles belong to the same franchise using word overlap.
    Calculates the percentage of shared words relative to the shorter title.
    """
    words1 = set(re.findall(r'\b\w+\b', title1.lower()))
    words2 = set(re.findall(r'\b\w+\b', title2.lower()))
    
    if not words1 or not words2:
        return False
        
    overlap = len(words1.intersection(words2))
    shorter_len = min(len(words1), len(words2))
    
    return (overlap / shorter_len) >= threshold


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
    
    franchises = {} # seed_name_lower -> aggregated_franchise_record
    
    for anime in search_results["data"]:
        # 1. Type, Genre & Rating Filtering
        if anime.get("type") not in allowed_types:
            continue
        if any(g["name"] in forbidden_genres for g in anime.get("genres", [])):
            continue
        if not anime.get("score") or anime.get("score") == 0:
            continue
            
        # 2. Aggregation by Word Overlap
        title = anime["title"]
        
        found_seed = None
        for existing_seed in franchises.keys():
            if is_same_franchise(title, existing_seed):
                found_seed = existing_seed
                break
        
        if not found_seed:
            franchises[title] = {
                "title": title,
                "type": anime.get("type"),
                "genres": [g["name"] for g in anime.get("genres", [])],
                "genre_ids": [g["mal_id"] for g in anime.get("genres", [])],
                "themes": [t["name"] for t in anime.get("themes", [])],
                "demographics": [d["name"] for d in anime.get("demographics", [])],
                "score": anime.get("score") or 0,
                "rank": anime.get("rank"),
                "popularity": anime.get("popularity"),
                "members": anime.get("members"),
                "images": anime.get("images"),
                "mal_id": anime.get("mal_id")
            }
        else:
            # 3. Aggregate metadata into the franchise
            f = franchises[found_seed]
            
            # Combine Lists
            for key in ["genres", "themes", "demographics"]:
                existing = set(f[key])
                existing.update(x["name"] for x in anime.get(key, []))
                f[key] = list(existing)
            
            # Combine Genre IDs specifically for recommendation logic
            existing_ids = set(f["genre_ids"])
            existing_ids.update(g["mal_id"] for g in anime.get("genres", []))
            f["genre_ids"] = list(existing_ids)
            
            f["score"] = max(f["score"], anime.get("score") or 0)
            f["members"] = (f["members"] or 0) + (anime.get("members") or 0)
            
            # 4. Promote TV series as the display representative (Hero)
            if anime.get("type") == "TV" and f["type"] != "TV":
                f["images"] = anime.get("images")
                f["type"] = "TV"
                f["mal_id"] = anime.get("mal_id")
                f["rank"] = anime.get("rank")
                f["popularity"] = anime.get("popularity")
                
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
    recommendations = [r["entry"]["title"] for r in recs_res["data"][:3]]
    
    # Extract only the requested metadata to save on API calls and keep the JSON clean.
    data = {
        "Anime Name": selected_anime["title"],
        "Genres": selected_anime.get("genres", []),
        "Demographics": selected_anime.get("demographics", []),
        "Themes": selected_anime.get("themes", []),
        "Recommendations": recommendations,
        "Rank": selected_anime.get("rank"),
        "Popularity": selected_anime.get("popularity"),
        "Members": selected_anime.get("members"),
        "Image URL": selected_anime.get("images", {}).get("webp", {}).get("large_image_url"),
        "MAL_ID": selected_anime.get("mal_id")
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
    source_title = selected_anime["title"]
    
    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]
    
    franchises = {} # representative_title -> { "Clean Name": str, "Versions": [] }

    for anime in search_results["data"]:
        title = anime["title"]
        
        # 1. Skip the reference anime, its sequels, and anything already seen in this chain.
        is_seen = False
        for seen_title in seen_franchises:
            if is_same_franchise(title, seen_title):
                is_seen = True
                break
                
        if is_seen or is_same_franchise(title, source_title):
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
        found_group_key = None
        for rep_title in franchises.keys():
            if is_same_franchise(title, rep_title):
                found_group_key = rep_title
                break
                
        if not found_group_key:
            found_group_key = title
            franchises[found_group_key] = {
                "Clean Name": title,
                "Versions": []
            }
        
        # Store this specific version's metadata
        franchises[found_group_key]["Versions"].append({
            "Title": title,
            "Genres": {g["name"] for g in anime_genres},
            "Demographics": {d["name"] for d in anime.get("demographics", [])},
            "Themes": {t["name"] for t in anime.get("themes", [])},
            "Score": anime.get("score") or 0,
            "Rank": anime.get("rank") or 999999,
            "Popularity": anime.get("popularity") or 999999,
            "Members": anime.get("members") or 0,
            "Image URL": anime.get("images", {}).get("webp", {}).get("large_image_url"),
            "MAL_ID": anime.get("mal_id")
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
            "MAL Score": max(scores) if scores else 0,
            "Image URL": versions[0]["Image URL"] if versions else None,
            "MAL_ID": versions[0]["MAL_ID"] if versions else None
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
        history.add(selected_anime['title'])
        
        print(f"\n--- Reference Anime: {selected_anime['title']} ---")
        
        # 1. Generate and print JSON for the reference anime only.
        metadata = fetch_anime_details(selected_anime)
        print(json.dumps(metadata, indent=4, ensure_ascii=True))
        
        # 2. Extract genres and find top 25 candidates.
        print(f"\nFinding top 25 candidates with matching genres...")
        genre_ids = selected_anime.get("genre_ids", [])
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
