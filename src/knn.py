"""
K-Nearest Neighbors (KNN) Vectorization Tool
===========================================
This module provides utility functions to convert anime metadata into 
normalized feature vectors, allowing for similarity comparisons.
"""

import json
import math


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
    vector.append(round(rank / max_rank, 4) * W_TIEBREAKER if max_rank > 0 else 0)
    
    # 6. Normalized Popularity
    pop = anime_data.get("Popularity") or max_pop
    vector.append(round(pop / max_pop, 4) * W_TIEBREAKER if max_pop > 0 else 0)
    
    # 7. Normalized Members
    mem = anime_data.get("Members") or 0
    vector.append(round(mem / max_mem, 4) * W_TIEBREAKER if max_mem > 0 else 0)
    
    return vector


def process_vectors(ref_data, candidate_pool_data, chain_depth=0):
    """
    Coordinates the vectorization process with normalized weights that sum to 10.
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
    
    print(f"\n--- Weight Distribution (Total: 10.0) ---")
    for k, v in weights.items():
        print(f"  {k}: {v} ({int(v*10)}% importance)")
    

    # Calculate Normalization Maxima across the entire pool.
    max_rank = max((a.get("Rank") or 0) for a in all_anime)
    max_pop = max((a.get("Popularity") or 0) for a in all_anime)
    max_mem = max((a.get("Members") or 0) for a in all_anime)
    
    # Define Target Vocabulary based strictly on the Reference Anime.
    target_genres = ref_data.get("Genres", [])
    target_themes = ref_data.get("Themes", [])
    target_demos = ref_data.get("Demographics", [])
    target_recommendations = set(ref_data.get("Recommendations", []))
    
    print("\n--- KNN Vectors [Genres, Themes, Demographics, Recommendations, Rank_Norm, Pop_Norm, Mem_Norm] ---")
    
    # Generate the reference vector first
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
    print(f"{ref_data['Anime Name']} (Ref): {ref_vector}")
    
    best_score = -1
    best_match = None
    
    print("\n--- Similarity Scores ---")
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
        
        # Calculate similarity against the reference
        score = calculate_cosine_similarity(ref_vector, candidate_vector)
        print(f"{anime['Anime Name']}: {round(score, 4)}")
        
        if score > best_score:
            best_score = score
            best_match = anime['Anime Name']
            
    if best_match:
        print(f"\n>>> Top Match: {best_match} (Score: {round(best_score, 4)}) <<<")
        
    return best_match
