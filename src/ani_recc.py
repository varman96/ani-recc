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
import logging
import time

logger = logging.getLogger(__name__)
DEFAULT_REQUEST_TIMEOUT = 10
MIN_JIKAN_REQUEST_INTERVAL = 0.34
_LAST_JIKAN_REQUEST_AT = 0.0


def _get_jikan_json(url, *, params=None, context="Jikan request"):
    """
    Performs a single Jikan request with a shared timeout and unified failure handling.
    Any failure raises immediately so callers do not silently continue with partial data.
    """
    global _LAST_JIKAN_REQUEST_AT

    try:
        now = time.monotonic()
        elapsed = now - _LAST_JIKAN_REQUEST_AT
        if elapsed < MIN_JIKAN_REQUEST_INTERVAL:
            time.sleep(MIN_JIKAN_REQUEST_INTERVAL - elapsed)

        response = requests.get(url, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)
        _LAST_JIKAN_REQUEST_AT = time.monotonic()
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout as e:
        logger.error("%s timed out after %ss: %s", context, DEFAULT_REQUEST_TIMEOUT, url)
        raise RuntimeError(f"{context} timed out after {DEFAULT_REQUEST_TIMEOUT}s") from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        logger.error("%s failed with HTTP %s: %s", context, status_code, url)
        raise RuntimeError(f"{context} failed with HTTP {status_code}") from e
    except requests.exceptions.RequestException as e:
        logger.error("%s failed: %s", context, e)
        raise RuntimeError(f"{context} failed: {e}") from e
    except json.JSONDecodeError as e:
        logger.error("%s returned invalid JSON: %s", context, url)
        raise RuntimeError(f"{context} returned invalid JSON") from e

def get_franchise_mal_ids(mal_id):
    """
    Fetches all related anime MAL IDs for a given seed anime to build a franchise lookup set.
    Fails immediately on request errors so callers do not continue with partial data.
    """
    base_url = f"https://api.jikan.moe/v4/anime/{mal_id}/relations"
    related_ids = {mal_id} # Always include the seed itself

    relations_data = _get_jikan_json(base_url, context=f"Fetching relations for MAL ID {mal_id}").get("data", [])
    for relation in relations_data:
        for entry in relation.get("entry", []):
            if entry.get("type") == "anime":
                related_ids.add(entry.get("mal_id"))
    
    return related_ids

def is_same_franchise(target_mal_id, franchise_mal_ids_set):
    """
    Checks if a target anime belongs to a franchise using a pre-computed lookup set.
    """
    return target_mal_id in franchise_mal_ids_set


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
    search_results = _get_jikan_json(base_url, params=params, context=f"Searching anime for query '{query}'")
    
    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]
    
    franchises = {} # seed_mal_id -> aggregated_franchise_record
    
    for anime in search_results["data"]:
        # 1. Type, Genre & Rating Filtering
        if anime.get("type") not in allowed_types:
            continue
        if any(g["name"] in forbidden_genres for g in anime.get("genres", [])):
            continue
        if not anime.get("score") or anime.get("score") == 0:
            continue
            
        # 2. Aggregation by Relation Lookup
        anime_mal_id = anime["mal_id"]
        found_seed = None
        for existing_seed_id, f_data in franchises.items():
            if is_same_franchise(anime_mal_id, f_data["franchise_ids"]):
                found_seed = existing_seed_id
                break
        
        if found_seed is None:
            franchise_ids = get_franchise_mal_ids(anime_mal_id)
            title = anime["title"]
            franchises[anime_mal_id] = {
                "franchise_ids": franchise_ids,
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
    recs_res = _get_jikan_json(base_url, context=f"Fetching recommendations for MAL ID {mal_id}")
    
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


def fetch_anime_by_mal_id(mal_id):
    """
    Fetches the full anime record for a MAL ID from Jikan.
    """
    base_url = f"https://api.jikan.moe/v4/anime/{mal_id}"
    anime = _get_jikan_json(base_url, context=f"Fetching anime details for MAL ID {mal_id}").get("data", {})
    if anime and "genre_ids" not in anime:
        anime["genre_ids"] = [g.get("mal_id") for g in anime.get("genres", []) if g.get("mal_id") is not None]
    return anime


def get_recommendation_by_mal_id(mal_id, history=None, chain_depth=0, limit=25):
    """
    Builds a recommendation payload directly from a MAL ID.
    """
    selected_anime = fetch_anime_by_mal_id(mal_id)
    if not selected_anime:
        return {
            "reference": None,
            "top_match": None,
            "all_candidates": [],
            "message": f"No anime found for MAL ID '{mal_id}'."
        }

    metadata = fetch_anime_details(selected_anime)

    history_set = set(history or [])
    history_set.add(selected_anime["mal_id"])

    genre_ids = selected_anime.get("genre_ids", [])
    candidates = get_top_candidates_by_genre(genre_ids, selected_anime, history_set, limit=limit)

    if not candidates:
        return {
            "reference": metadata,
            "top_match": None,
            "all_candidates": [],
            "message": "No suitable candidates found for recommendation."
        }

    top_match_name = knn.process_vectors(metadata, candidates, chain_depth=chain_depth)
    top_match_data = next((c for c in candidates if c["Anime Name"] == top_match_name), None)

    return {
        "reference": metadata,
        "top_match": {
            "name": top_match_name,
            "data": top_match_data
        },
        "all_candidates": candidates[:10]
    }


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
    search_results = _get_jikan_json(base_url, params=params, context=f"Fetching candidate pool for MAL ID {selected_anime['mal_id']}")

    source_genre_ids = set(genre_ids)
    source_mal_id = selected_anime["mal_id"]
    logger.info("Fetching relations for source anime: %s...", selected_anime["title"])
    source_franchise_ids = get_franchise_mal_ids(source_mal_id)
    
    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]
    
    franchises = {} # representative_mal_id -> { "Clean Name": str, "Versions": [], "franchise_ids": set }

    for anime in search_results["data"]:
        title = anime["title"]
        anime_mal_id = anime["mal_id"]
        
        # 1. Skip the reference anime, its sequels, and anything already seen in this chain.
        if anime_mal_id in seen_franchises or is_same_franchise(anime_mal_id, source_franchise_ids):
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
        for rep_id, f_data in franchises.items():
            if is_same_franchise(anime_mal_id, f_data["franchise_ids"]):
                found_group_key = rep_id
                break
                
        if found_group_key is None:
            found_group_key = anime_mal_id
            franchise_ids = get_franchise_mal_ids(anime_mal_id)
            franchises[found_group_key] = {
                "franchise_ids": franchise_ids,
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

    def select_anime(results, current_query, chain_depth):
        """
        Handles both auto-selection and manual selection.
        """
        if chain_depth > 0 and results[0]["title"].lower() == current_query.lower():
            return results[0]

        logger.info("--- Search Results ---")
        for i, anime in enumerate(results, start=1):
            logger.info("[%s] %s", i, anime["title"])

        try:
            choice_raw = input("\nPick a number (1-5) or 0 to cancel: ")
            if not choice_raw.strip():
                return None
            choice = int(choice_raw)
            if choice == 0:
                logger.warning("Operation cancelled.")
                return None
            return results[choice - 1]
        except (ValueError, IndexError):
            logger.warning("Invalid selection.")
            return None

    def consolidate(selected_anime, history, chain_depth):
        """
        Consolidates metadata fetching, candidate fetching, and KNN processing.
        """
        history.add(selected_anime["mal_id"])

        logger.info("--- Reference Anime: %s ---", selected_anime["title"])

        metadata = fetch_anime_details(selected_anime)
        logger.info(json.dumps(metadata, indent=4, ensure_ascii=True))

        logger.info("Finding top 25 candidates with matching genres...")
        genre_ids = selected_anime.get("genre_ids", [])
        candidates = get_top_candidates_by_genre(genre_ids, selected_anime, history)

        if not candidates:
            logger.warning("No new candidates found in this chain! Try a fresh search.")
            return None, None

        logger.info("--- Candidate Pool (Aggregated Franchises) ---")
        for i, anime in enumerate(candidates, start=1):
            version_text = f"({anime['Version Count']} versions)"
            score_display = f"(Avg Score: {round(anime['MAL Score'], 2)})"
            logger.info("[%s] %s %s %s", i, anime["Anime Name"], version_text, score_display)

        top_match_name = knn.process_vectors(metadata, candidates, chain_depth)
        return top_match_name, candidates

    def manage_loop():
        """
        Manages the session state and overall interactive loop.
        """
        history = set()
        chain_depth = 0
        current_query = args.title

        while True:
            if not current_query:
                current_query = input("\nEnter the name of the anime (or 'exit' to quit): ")
                if current_query.lower() == "exit":
                    break
                history = set()
                chain_depth = 0

                logger.info("Searching for matches for '%s'...", current_query)
                results = search_anime(current_query)

            if not results:
                logger.warning("No results found. Please try a different title.")
                current_query = None
                continue

            selected_anime = select_anime(results, current_query, chain_depth)
            if not selected_anime:
                current_query = None
                continue

            top_match_name, _ = consolidate(selected_anime, history, chain_depth)
            if top_match_name is None:
                current_query = None
                continue

            prompt = "\n[R] Refresh (New Search) | [X] Exit"
            if top_match_name:
                prompt += f" | [C] Continue with '{top_match_name}'"

            action = input(f"{prompt}: ").lower()

            if action == "x":
                break
            elif action == "c" and top_match_name:
                current_query = top_match_name
                chain_depth += 1
            else:
                current_query = None

    manage_loop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
