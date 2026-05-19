"""
K-Nearest Neighbors (KNN) Vectorization Tool
===========================================
This module provides utility functions to convert anime metadata into 
normalized feature vectors, allowing for similarity comparisons.
"""

import logging
import math

logger = logging.getLogger(__name__)

_BANDIT_STATE = {
    "candidates": {},
    "total_tries": 0,
}

_UNSEEN_UCB_SCORE = 9999.0

def calculate_cosine_similarity(vec1, vec2):
    """
    Calculates the cosine similarity between two vectors.
    
    Args:
        vec1 (list): First vector.
        vec2 (list): Second vector.
        
    Returns:
        float: Similarity score between 0 and 1.
    """
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
        
    return dot_product / (magnitude1 * magnitude2)


def reset_bandit_session():
    """
    Clears the in-session bandit state.
    """
    _BANDIT_STATE["candidates"] = {}
    _BANDIT_STATE["total_tries"] = 0


def _candidate_key(candidate):
    """
    Returns a stable identifier for bandit bookkeeping.
    """
    candidate_id = candidate.get("MAL_ID")
    if candidate_id is not None:
        return f"mal_id:{candidate_id}"
    return f"name:{candidate.get('Anime Name', '')}"


def _get_bandit_record(candidate):
    """
    Fetches or initializes the bandit record for a candidate.
    """
    key = _candidate_key(candidate)
    record = _BANDIT_STATE["candidates"].get(key)
    if record is None:
        record = {"q": 0.0, "n": 0}
        _BANDIT_STATE["candidates"][key] = record
    return key, record


def score_candidate_pool(ref_vector, candidate_pool_data, *, exploration_constant=1.25):
    """
    Scores candidates against the reference vector and decorates them with bandit state.
    """
    scored_candidates = []
    total_tries = max(1, _BANDIT_STATE["total_tries"])

    for candidate in candidate_pool_data:
        candidate_vector = candidate.get("_vector")
        similarity = candidate.get("cosine_similarity")
        if similarity is None:
            similarity = calculate_cosine_similarity(ref_vector, candidate_vector)

        key, bandit_record = _get_bandit_record(candidate)
        visits = bandit_record["n"]
        q_value = bandit_record["q"]

        if visits == 0:
            ucb_score = _UNSEEN_UCB_SCORE
        else:
            ucb_score = q_value + exploration_constant * math.sqrt(math.log(total_tries) / visits)

        scored_candidate = dict(candidate)
        scored_candidate["bandit_key"] = key
        scored_candidate["bandit_q"] = round(q_value, 4)
        scored_candidate["bandit_n"] = visits
        scored_candidate["ucb_score"] = ucb_score
        scored_candidates.append(scored_candidate)

    scored_candidates.sort(key=lambda item: item["ucb_score"], reverse=True)
    return scored_candidates


def select_candidate_with_bandit(scored_candidates):
    """
    Selects the surfaced recommendation using the UCB policy.
    """
    if not scored_candidates:
        return None

    selected_candidate = max(
        scored_candidates,
        key=lambda item: (
            item["ucb_score"],
            item["cosine_similarity"],
            -item.get("bandit_n", 0),
        ),
    )
    logger.info(
        "Bandit selected %s with UCB=%s and cosine=%s",
        selected_candidate.get("Anime Name"),
        round(selected_candidate["ucb_score"], 4),
        round(selected_candidate["cosine_similarity"], 4),
    )
    return selected_candidate


def record_feedback(candidate, thumbs_up):
    """
    Updates the bandit estimate for a surfaced candidate.
    """
    if candidate is None:
        return None

    key, bandit_record = _get_bandit_record(candidate)
    reward = 1.0 if thumbs_up else -1.0
    bandit_record["n"] += 1
    _BANDIT_STATE["total_tries"] += 1
    previous_n = bandit_record["n"] - 1
    if previous_n <= 0:
        bandit_record["q"] = reward
    else:
        bandit_record["q"] = ((bandit_record["q"] * previous_n) + reward) / bandit_record["n"]

    logger.info(
        "Bandit updated for %s: Q=%s N=%s",
        key,
        round(bandit_record["q"], 4),
        bandit_record["n"],
    )
    return {
        "bandit_key": key,
        "q": bandit_record["q"],
        "n": bandit_record["n"],
    }


def create_vector(anime_data, target_genres, target_themes, target_demos, target_recommendations, max_rank, max_pop, max_mem, weights, is_ref=False):
    """
    Converts individual anime metadata into a weighted feature vector.
    """
    vector = []
    
    # Extract dynamic weights
    W_GENRE = weights["GENRE"]
    W_DEMO = weights["DEMO"]
    W_THEME = weights["THEME"]
    W_REC = weights["REC"]
    W_TIEBREAKER = weights["TIEBREAKER"]
    
    # 1. Binary Genres
    current_genres = set(anime_data.get("Genres", []))
    for g in target_genres:
        match = 1 if g in current_genres else 0
        vector.append(match * W_GENRE)
        
    # 2. Binary Themes
    current_themes = set(anime_data.get("Themes", []))
    for t in target_themes:
        match = 1 if t in current_themes else 0
        vector.append(match * W_THEME)

    # 3. Binary Demographics
    current_demos = set(anime_data.get("Demographics", []))
    for d in target_demos:
        match = 1 if d in current_demos else 0
        vector.append(match * W_DEMO)
        
    # 4. Binary Recommendations
    if is_ref:
        vector.append(W_REC)
    else:
        match = 1 if anime_data.get("Anime Name") in target_recommendations else 0
        vector.append(match * W_REC)

    # 5. Normalized Rank
    rank = anime_data.get("Rank") or max_rank
    vector.append(round((max_rank - rank) / max_rank, 4) * W_TIEBREAKER if max_rank > 0 else 0)
    
    # 6. Normalized Popularity
    pop = anime_data.get("Popularity") or max_pop
    vector.append(round((max_pop - pop) / max_pop, 4) * W_TIEBREAKER if max_pop > 0 else 0)
    
    # 7. Normalized Members
    mem = anime_data.get("Members") or 0
    vector.append(round(mem / max_mem, 4) * W_TIEBREAKER if max_mem > 0 else 0)
    
    return vector


def process_vectors(ref_data, candidate_pool_data, chain_depth=0):
    """
    Coordinates vector creation and similarity scoring for the candidate pool.
    """
    all_anime = [ref_data] + candidate_pool_data
    
    # 1. Assign "Priority Points" (Original Drift Intensity)
    # Starting ratios: Genre(8.0), Demo(5.0), Theme(7.0), Rec(1.0)
    p_genre = max(1.0, 8.0 - chain_depth * 1.5)
    p_demo = max(1.0, 5.0 - chain_depth * 1.0)
    p_theme = 7.0 + (chain_depth * 1.0)
    p_rec = 1.0 + (chain_depth * 2.0)
    p_tiebreaker = 0.1
    
    total_points = p_genre + p_demo + p_theme + p_rec + p_tiebreaker
    
    # 2. Normalize to a Scale of 10 (Total Score = 10.0)
    # This ensures each weight represents a percentage of importance (e.g., 6.0 = 60%)
    weights = {
        "GENRE": round((p_genre / total_points) * 10, 2),
        "DEMO": round((p_demo / total_points) * 10, 2),
        "THEME": round((p_theme / total_points) * 10, 2),
        "REC": round((p_rec / total_points) * 10, 2),
        "TIEBREAKER": round((p_tiebreaker / total_points) * 10, 2)
    }
    
    # Ensure sum is exactly 10.0 (compensate for rounding)
    diff = 10.0 - sum(weights.values())
    weights["THEME"] = round(weights["THEME"] + diff, 2)
    
    logger.info("--- Weight Distribution (Total: 10.0) ---")
    for k, v in weights.items():
        logger.info("  %s: %s (%s%% importance)", k, v, round(v * 10))
    

    # Calculate Normalization Maxima across the entire pool.
    max_rank = max((a.get("Rank") or 0) for a in all_anime)
    max_pop = max((a.get("Popularity") or 0) for a in all_anime)
    max_mem = max((a.get("Members") or 0) for a in all_anime)
    
    # Define Target Vocabulary based strictly on the Reference Anime.
    target_genres = ref_data.get("Genres", [])
    target_themes = ref_data.get("Themes", [])
    target_demos = ref_data.get("Demographics", [])
    target_recommendations = set(ref_data.get("Recommendations", []))
    
    logger.info("--- KNN Vectors [Genres, Themes, Demographics, Recommendations, Rank_Norm, Pop_Norm, Mem_Norm] ---")

    ref_vector = create_vector(
        ref_data, 
        target_genres, 
        target_themes, 
        target_demos,
        target_recommendations,
        max_rank, 
        max_pop, 
        max_mem,
        weights,
        is_ref=True
    )
    logger.info("%s (Ref): %s", ref_data["Anime Name"], ref_vector)

    scored_candidates = []
    logger.info("--- Similarity Scores ---")
    for anime in candidate_pool_data:
        candidate_vector = create_vector(
            anime, 
            target_genres, 
            target_themes, 
            target_demos,
            target_recommendations,
            max_rank, 
            max_pop, 
            max_mem,
            weights,
            is_ref=False
        )
        score = calculate_cosine_similarity(ref_vector, candidate_vector)
        logger.info("%s: %s", anime["Anime Name"], round(score, 4))
        scored_candidates.append({
            **anime,
            "_vector": candidate_vector,
            "cosine_similarity": score,
        })

    return score_candidate_pool(ref_vector, scored_candidates)
