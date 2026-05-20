"""
Anime Library Tool
==================
This script allows users to search for anime titles using the Jikan API,
extract key metadata, and display it as a JSON-based structure.
"""

import time
import requests
import json
import logging
import threading
import argparse
from pathlib import Path
import knn

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 5
MIN_JIKAN_REQUEST_INTERVAL = 0.34  # Jikan's ~3 req/sec limit
_LAST_JIKAN_REQUEST_AT = (
    time.monotonic() - MIN_JIKAN_REQUEST_INTERVAL
)  # Allow immediate first call
_rate_lock = threading.Lock()  # Thread-safe pacing (optional but recommended)
MAX_CHAIN_DEPTH = 5
CACHE_TTL_SECONDS = 24 * 60 * 60
JIKAN_CACHE_PATH = (
    Path(__file__).resolve().parents[1] / ".cache" / "jikan_response_cache.json"
)
_JIKAN_CACHE = None
_jikan_cache_lock = threading.Lock()


def _validate_positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _extract_mal_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, dict):
        for key in ("mal_id", "MAL_ID", "id"):
            extracted = value.get(key)
            if (
                isinstance(extracted, int)
                and not isinstance(extracted, bool)
                and extracted > 0
            ):
                return extracted
    return None


def _validate_history(history):
    if history is None:
        return []
    if not isinstance(history, list):
        raise TypeError("history must be a flat list of integers")
    normalized = []
    for item in history:
        mal_id = _extract_mal_id(item)
        if mal_id is None:
            raise ValueError("history must be a flat list of integers")
        normalized.append(mal_id)
    return normalized


def _validate_chain_depth(chain_depth):
    if isinstance(chain_depth, bool) or not isinstance(chain_depth, int):
        raise TypeError("chain_depth must be an integer")
    if not 0 <= chain_depth <= MAX_CHAIN_DEPTH:
        raise ValueError(f"chain_depth must be between 0 and {MAX_CHAIN_DEPTH}")


def _build_jikan_cache_key(url, params=None):
    return requests.Request("GET", url, params=params).prepare().url


def _load_jikan_cache_unlocked():
    global _JIKAN_CACHE

    if _JIKAN_CACHE is not None:
        return _JIKAN_CACHE

    try:
        with JIKAN_CACHE_PATH.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, json.JSONDecodeError):
        cache = {}

    now = time.time()
    _JIKAN_CACHE = {
        key: value
        for key, value in cache.items()
        if isinstance(value, dict)
        and isinstance(value.get("ts"), (int, float))
        and now - value["ts"] < CACHE_TTL_SECONDS
        and "value" in value
    }
    return _JIKAN_CACHE


def _save_jikan_cache_unlocked(cache):
    JIKAN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JIKAN_CACHE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=True, indent=2)


def clear_jikan_cache():
    """
    Clears the in-memory and on-disk Jikan response cache.
    """
    global _JIKAN_CACHE

    with _jikan_cache_lock:
        _JIKAN_CACHE = {}
        try:
            JIKAN_CACHE_PATH.unlink()
        except FileNotFoundError:
            pass


def _get_jikan_json(url, *, params=None, context="Jikan request"):
    """
    Performs a single Jikan request with dynamic rate limiting, strict timeout,
    and unified failure handling. Fails immediately on any error.
    """
    global _LAST_JIKAN_REQUEST_AT

    cache_key = _build_jikan_cache_key(url, params=params)
    now = time.time()

    with _jikan_cache_lock:
        cache = _load_jikan_cache_unlocked()
        cached_entry = cache.get(cache_key)
        if cached_entry and now - cached_entry["ts"] < CACHE_TTL_SECONDS:
            return cached_entry["value"]
        if cached_entry:
            cache.pop(cache_key, None)
            _save_jikan_cache_unlocked(cache)

    with _rate_lock:
        now = time.monotonic()
        elapsed = now - _LAST_JIKAN_REQUEST_AT
        if elapsed < MIN_JIKAN_REQUEST_INTERVAL:
            time.sleep(MIN_JIKAN_REQUEST_INTERVAL - elapsed)

        response = requests.get(url, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)
        _LAST_JIKAN_REQUEST_AT = time.monotonic()

    try:
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.Timeout as e:
        logger.error(
            "%s timed out after %ss: %s", context, DEFAULT_REQUEST_TIMEOUT, url
        )
        raise RuntimeError(
            f"{context} timed out after {DEFAULT_REQUEST_TIMEOUT}s"
        ) from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        logger.error("%s failed with HTTP %s: %s", context, status_code, url)
        raise RuntimeError(f"{context} failed with HTTP {status_code}") from e
    except requests.exceptions.RequestException as e:
        logger.error("%s network error: %s", context, e)
        raise RuntimeError(f"{context} network error: {e}") from e
    except json.JSONDecodeError as e:
        logger.error("%s returned invalid JSON: %s", context, url)
        raise RuntimeError(f"{context} returned invalid JSON") from e

    with _jikan_cache_lock:
        cache = _load_jikan_cache_unlocked()
        cache[cache_key] = {"ts": time.time(), "value": payload}
        _save_jikan_cache_unlocked(cache)

    return payload


def get_franchise_mal_ids(mal_id):
    """
    Fetches all related anime MAL IDs for a given seed anime to build a franchise lookup set.
    Fails immediately on request errors so callers do not continue with partial data.
    """
    _validate_positive_int(mal_id, "mal_id")
    base_url = f"https://api.jikan.moe/v4/anime/{mal_id}/relations"
    related_ids = {mal_id}  # Always include the seed itself

    relations_data = _get_jikan_json(
        base_url, context=f"Fetching relations for MAL ID {mal_id}"
    ).get("data", [])
    for relation in relations_data:
        for entry in relation.get("entry", []):
            if entry.get("type") == "anime":
                related_id = _extract_mal_id(entry)
                if related_id is not None:
                    related_ids.add(related_id)

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
    search_results = _get_jikan_json(
        base_url, params=params, context=f"Searching anime for query '{query}'"
    )

    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]

    franchises = {}  # seed_mal_id -> aggregated_franchise_record

    for anime in search_results["data"]:
        # 1. Type, Genre & Rating Filtering
        if anime.get("type") not in allowed_types:
            continue
        if any(g["name"] in forbidden_genres for g in anime.get("genres", [])):
            continue
        if not anime.get("score") or anime.get("score") == 0:
            continue

        # 2. Aggregation by Relation Lookup
        anime_mal_id = anime.get("mal_id")
        if not anime_mal_id:
            continue
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
                "mal_id": anime.get("mal_id"),
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
    mal_id = selected_anime.get("mal_id")
    if not mal_id:
        raise ValueError("Selected anime record is missing a valid 'mal_id' field.")
    base_url = f"https://api.jikan.moe/v4/anime/{mal_id}/recommendations"
    recs_res = _get_jikan_json(
        base_url, context=f"Fetching recommendations for MAL ID {mal_id}"
    )

    # Clean the recommendation titles and take ONLY the top 3
    recommendations = [r["entry"]["title"] for r in recs_res["data"][:3]]

    def _normalize_feature_list(values):
        normalized = []
        for value in values or []:
            if isinstance(value, str):
                if value:
                    normalized.append(value)
            elif isinstance(value, dict):
                name = value.get("name")
                if name:
                    normalized.append(name)
        return normalized

    genres = _normalize_feature_list(selected_anime.get("genres", []))
    demographics = _normalize_feature_list(selected_anime.get("demographics", []))
    themes = _normalize_feature_list(selected_anime.get("themes", []))

    # Extract only the requested metadata to save on API calls and keep the JSON clean.
    data = {
        "Anime Name": selected_anime["title"],
        "Genres": genres,
        "Demographics": demographics,
        "Themes": themes,
        "Recommendations": recommendations,
        "Rank": selected_anime.get("rank"),
        "Popularity": selected_anime.get("popularity"),
        "Members": selected_anime.get("members"),
        "Image URL": selected_anime.get("images", {})
        .get("webp", {})
        .get("large_image_url"),
        "MAL_ID": selected_anime.get("mal_id"),
    }

    return data


def fetch_anime_by_mal_id(mal_id):
    """
    Fetches the full anime record for a MAL ID from Jikan.
    """
    _validate_positive_int(mal_id, "mal_id")
    base_url = f"https://api.jikan.moe/v4/anime/{mal_id}"
    anime = _get_jikan_json(
        base_url, context=f"Fetching anime details for MAL ID {mal_id}"
    ).get("data", {})
    if anime and "genre_ids" not in anime:
        anime["genre_ids"] = [
            g.get("mal_id")
            for g in anime.get("genres", [])
            if g.get("mal_id") is not None
        ]
    return anime


def get_recommendation_by_mal_id(mal_id, history=None, chain_depth=0, limit=25):
    """
    Builds a recommendation payload directly from a MAL ID.
    """
    _validate_positive_int(mal_id, "mal_id")
    history = _validate_history(history)
    _validate_chain_depth(chain_depth)
    if chain_depth == 0:
        knn.reset_bandit_session()

    selected_anime = fetch_anime_by_mal_id(mal_id)
    if not selected_anime:
        return {
            "reference": None,
            "top_match": None,
            "all_candidates": [],
            "message": f"No anime found for MAL ID '{mal_id}'.",
        }

    metadata = fetch_anime_details(selected_anime)

    history_set = set(_validate_history(history))
    selected_mal_id = _extract_mal_id(selected_anime.get("mal_id")) or _extract_mal_id(
        selected_anime
    )
    if selected_mal_id is None:
        raise ValueError("selected anime is missing a valid mal_id")
    history_set.add(selected_mal_id)

    genre_ids = selected_anime.get("genre_ids", [])
    candidates = get_top_candidates_by_genre(
        genre_ids, selected_anime, history_set, limit=limit
    )

    if not candidates:
        return {
            "reference": metadata,
            "top_match": None,
            "all_candidates": [],
            "message": "No suitable candidates found for recommendation.",
        }

    scored_candidates = knn.process_vectors(
        metadata, candidates, chain_depth=chain_depth
    )
    selected_candidate = knn.select_candidate_with_bandit(scored_candidates)
    if selected_candidate is None:
        return {
            "reference": metadata,
            "top_match": None,
            "all_candidates": scored_candidates[:10],
            "message": "No suitable candidates found for recommendation.",
        }

    return {
        "reference": metadata,
        "top_match": {
            "name": selected_candidate["Anime Name"],
            "data": selected_candidate,
        },
        "all_candidates": scored_candidates[:10],
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
        "limit": 25,
    }
    search_results = _get_jikan_json(
        base_url,
        params=params,
        context=f"Fetching candidate pool for MAL ID {selected_anime['mal_id']}",
    )

    source_genre_ids = {
        genre_id
        for genre_id in genre_ids
        if isinstance(genre_id, int) and not isinstance(genre_id, bool)
    }
    source_mal_id = _extract_mal_id(selected_anime.get("mal_id")) or _extract_mal_id(
        selected_anime
    )
    if source_mal_id is None:
        raise ValueError("selected anime is missing a valid mal_id")
    logger.info("Fetching relations for source anime: %s...", selected_anime["title"])
    source_franchise_ids = get_franchise_mal_ids(source_mal_id)

    allowed_types = ["TV", "Movie"]
    forbidden_genres = ["Ecchi", "Erotica", "Hentai"]

    franchises = {}  # representative_mal_id -> { "Clean Name": str, "Versions": [], "franchise_ids": set }

    for anime in search_results["data"]:
        title = anime["title"]
        anime_mal_id = _extract_mal_id(anime.get("mal_id"))
        if anime_mal_id is None:
            continue

        # 1. Skip the reference anime, its sequels, and anything already seen in this chain.
        if anime_mal_id in seen_franchises or is_same_franchise(
            anime_mal_id, source_franchise_ids
        ):
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
        anime_genre_ids = {
            g["mal_id"]
            for g in anime_genres
            if isinstance(g.get("mal_id"), int)
            and not isinstance(g.get("mal_id"), bool)
        }
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
                "Versions": [],
            }

        # Store this specific version's metadata
        franchises[found_group_key]["Versions"].append(
            {
                "Title": title,
                "Genres": [g["name"] for g in anime_genres],
                "Demographics": [d["name"] for d in anime.get("demographics", [])],
                "Themes": [t["name"] for t in anime.get("themes", [])],
                "Score": anime.get("score") or 0,
                "Rank": anime.get("rank") or 999999,
                "Popularity": anime.get("popularity") or 999999,
                "Members": anime.get("members") or 0,
                "Image URL": anime.get("images", {})
                .get("webp", {})
                .get("large_image_url"),
                "MAL_ID": anime.get("mal_id"),
            }
        )

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

        final_candidates.append(
            {
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
                "MAL_ID": versions[0]["MAL_ID"] if versions else None,
            }
        )
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

    def prompt_recommendation_feedback(selected_candidate):
        """
        Captures thumbs up/down feedback for the surfaced recommendation.
        """
        if not selected_candidate:
            return

        response = (
            input(
                "\nRate this recommendation [U] Thumbs Up | [D] Thumbs Down | [S] Skip: "
            )
            .strip()
            .lower()
        )
        if response == "u":
            knn.record_feedback(selected_candidate, thumbs_up=True)
        elif response == "d":
            knn.record_feedback(selected_candidate, thumbs_up=False)

    def select_anime(results, current_query, chain_depth):
        """
        Handles both auto-selection and manual selection.
        """
        if chain_depth > 0:
            exact_match = next(
                (
                    anime
                    for anime in results
                    if anime["title"].lower() == current_query.lower()
                ),
                None,
            )
            if exact_match:
                return exact_match

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
            if choice < 1 or choice > len(results):
                logger.warning("Invalid selection: Number out of menu bounds.")
                return None
            return results[choice - 1]
        except ValueError:
            logger.warning("Invalid selection: Please enter a valid integer.")
            return None
        except (ValueError, IndexError):
            logger.warning("Invalid selection.")
            return None

    def consolidate(selected_anime, history, chain_depth):
        """
        Consolidates metadata fetching, candidate fetching, and KNN processing.
        """
        history.add(selected_anime["mal_id"])
        if chain_depth == 0:
            knn.reset_bandit_session()

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
            logger.info(
                "[%s] %s %s %s", i, anime["Anime Name"], version_text, score_display
            )

        scored_candidates = knn.process_vectors(metadata, candidates, chain_depth)
        selected_candidate = knn.select_candidate_with_bandit(scored_candidates)
        if selected_candidate is None:
            return None, scored_candidates
        return selected_candidate, scored_candidates

    def manage_loop():
        """
        Manages the session state and overall interactive loop.
        """
        history = set()
        chain_depth = 0
        current_query = args.title
        results = None

        while True:
            if not current_query:
                current_query = input(
                    "\nEnter the name of the anime (or 'exit' to quit): "
                )
                if current_query.lower() == "exit":
                    break
                history = set()
                chain_depth = 0
                results = None
                knn.reset_bandit_session()

            if results is None:
                clear_jikan_cache()
                logger.info("Searching for matches for '%s'...", current_query)
                results = search_anime(current_query)

            if not results:
                logger.warning("No results found. Please try a different title.")
                current_query = None
                results = None
                continue

            selected_anime = select_anime(results, current_query, chain_depth)
            if not selected_anime:
                current_query = None
                results = None
                continue

            selected_candidate, _ = consolidate(selected_anime, history, chain_depth)
            if selected_candidate is None:
                current_query = None
                results = None
                continue

            top_match_name = selected_candidate["Anime Name"]
            prompt_recommendation_feedback(selected_candidate)

            prompt = "\n[R] Refresh (New Search) | [X] Exit"
            if top_match_name:
                prompt += f" | [C] Continue with '{top_match_name}'"

            action = input(f"{prompt}: ").lower()

            if action == "x":
                clear_jikan_cache()
                break
            elif action == "c" and top_match_name:
                current_query = top_match_name
                chain_depth += 1
                results = None
            else:
                current_query = None
                results = None

    manage_loop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
