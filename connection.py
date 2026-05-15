import os

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import logging
from src import ani_recc

app = Flask(__name__)
app.json.ensure_ascii = False
CORS(app)

logger = logging.getLogger(__name__)


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in value]
    return value

@app.route('/')
def serve_index():
    return send_from_directory('front-end', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('front-end', path)

@app.route('/recommend', methods=['POST'])
def get_recommendation():
    """
    Endpoint to get anime recommendations based on a MAL ID.
    Expects JSON: {"mal_id": 12345}
    """
    data = request.get_json() or {}

    if "mal_id" not in data:
        return jsonify({"error": "Missing 'mal_id' in request body"}), 400

    try:
        result = ani_recc.get_recommendation_by_mal_id(
            data["mal_id"],
            history=data.get("history", []),
            chain_depth=data.get("chain_depth", 0)
        )
        return jsonify(_json_safe(result)), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

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
        return jsonify(_json_safe(results)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # Run on port 5000 by default
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Anime Recommendation API...")
    debug = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    app.run(debug=debug, host='127.0.0.1', port=5000)
