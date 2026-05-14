from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from src import ani_recc, knn
import os

app = Flask(__name__)
app.json.ensure_ascii = False
CORS(app)

@app.route('/')
def serve_index():
    return send_from_directory('front-end', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('front-end', path)

@app.route('/recommend', methods=['POST'])
def get_recommendation():
    """
    Endpoint to get anime recommendations based on a title.
    Expects JSON: {"title": "Anime Name"}
    """
    data = request.get_json()
    
    if not data or 'title' not in data:
        return jsonify({"error": "Missing 'title' in request body"}), 400
        
    title = data['title']
    history_list = data.get('history', [])
    chain_depth = data.get('chain_depth', 0)
    
    try:
        # 1. Search for the anime to get its metadata/mal_id
        search_results = ani_recc.search_anime(title)
        if not search_results:
            return jsonify({"error": f"No anime found matching '{title}'"}), 404
            
        # Select the first match as the reference
        selected_anime = search_results[0]
        
        # 2. Fetch full details (genres, themes, recommendations, etc.)
        metadata = ani_recc.fetch_anime_details(selected_anime)
        
        # 3. Find candidates with similar genres
        # Convert history list to set for O(1) lookups in the candidate search
        history = set(history_list)
        history.add(selected_anime['mal_id'])
        
        genre_ids = selected_anime.get('genre_ids', [])
        candidates = ani_recc.get_top_candidates_by_genre(genre_ids, selected_anime, history)
        
        if not candidates:
            return jsonify({
                "reference": metadata,
                "recommendation": None,
                "message": "No suitable candidates found for recommendation."
            }), 200

        # 4. Process vectors using KNN to find the top match
        # We use chain_depth=0 for the initial recommendation
        top_match_name = knn.process_vectors(metadata, candidates, chain_depth=chain_depth)
        
        # Find the full candidate data for the top match
        top_match_data = next((c for c in candidates if c['Anime Name'] == top_match_name), None)

        return jsonify({
            "reference": metadata,
            "top_match": {
                "name": top_match_name,
                "data": top_match_data
            },
            "all_candidates": candidates[:10] # Return top 10 candidates
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['GET'])
def search():
    """
    Endpoint to search for anime titles.
    Query param: ?q=title
    """
    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400
    
    try:
        results = ani_recc.search_anime(query)
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # Run on port 5000 by default
    print("Starting Anime Recommendation API...")
    app.run(debug=True, host='0.0.0.0', port=5000)
