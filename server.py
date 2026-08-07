"""
MovieBox API Server - Flask REST API
Scrapes themoviebox.xyz to search and download movies
Routes:
  GET /recherche?film=<query>&uid=<user_id>  - Search movies
  GET /stream?film=<index>&uid=<user_id>     - Get download/stream URL
  GET /detail?film=<index>&uid=<user_id>     - Get movie details
"""

import hashlib
import time
import json
import os
import logging
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Configuration
API_BASE = "https://h5-api.aoneroom.com"
ORIGIN = "https://themoviebox.xyz"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
RESULTS_CACHE_FILE = os.path.join(CACHE_DIR, "search_results.json")

# Cache for search results (uid -> results)
search_cache = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)

# Try to load persisted cache
try:
    if os.path.exists(RESULTS_CACHE_FILE):
        with open(RESULTS_CACHE_FILE, 'r') as f:
            search_cache = json.load(f)
        logger.info(f"Loaded {len(search_cache)} cached search results")
except Exception as e:
    logger.warning(f"Could not load cache: {e}")


def save_cache():
    """Persist search cache to disk."""
    try:
        with open(RESULTS_CACHE_FILE, 'w') as f:
            json.dump(search_cache, f)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")


def generate_client_token():
    """Generate X-Client-Token as done by the MovieBox frontend.
    
    Formula:
        timestamp = Math.floor(Date.now() / 1000)
        reversed_ts = timestamp.toString().split('').reverse().join('')
        md5_hash = MD5(reversed_ts)
        token = timestamp + ',' + md5_hash
    """
    ts = int(time.time())
    rev = str(ts)[::-1]
    md5_hash = hashlib.md5(rev.encode()).hexdigest()
    return f"{ts},{md5_hash}"


def create_authenticated_session():
    """Create an authenticated session with the MovieBox API.
    
    The flow:
    1. Generate a client token
    2. Make a GET request to everyone-search to obtain a cookie token
    3. Use the cookie token for subsequent POST requests
    """
    session = requests.Session()
    
    token = generate_client_token()
    
    headers = {
        'Origin': ORIGIN,
        'Referer': f'{ORIGIN}/',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Request-Lang': 'en',
        'X-Client-Token': token,
        'X-Client-Info': '{"timezone":"Indian/Antananarivo"}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # Step 1: Get cookie/session token
        resp = session.get(
            f'{API_BASE}/wefeed-h5api-bff/subject/everyone-search',
            headers=headers,
            timeout=10
        )
        
        if resp.status_code == 200:
            x_user = resp.headers.get('x-user', '')
            if x_user:
                user_data = json.loads(x_user)
                headers['Authorization'] = f"Bearer {user_data.get('token', '')}"
                logger.info("Successfully authenticated with MovieBox API")
            else:
                logger.warning("No x-user header in response")
        else:
            logger.error(f"Auth GET failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"Auth error: {e}")
    
    return session, headers


def search_movies(session, headers, keyword, page=1, per_page=20):
    """Search for movies using the MovieBox API."""
    data = {
        "keyword": keyword,
        "page": page,
        "perPage": per_page,
        "subjectType": 0  # 0 = all, 1 = movies, 2 = series
    }
    
    resp = session.post(
        f'{API_BASE}/wefeed-h5api-bff/subject/search',
        headers=headers,
        json=data,
        timeout=15
    )
    
    if resp.status_code != 200:
        logger.error(f"Search failed: {resp.status_code} - {resp.text[:200]}")
        return None
    
    return resp.json()


def get_movie_detail(session, headers, subject_id):
    """Get detailed information about a movie."""
    resp = session.get(
        f'{API_BASE}/wefeed-h5api-bff/detail',
        headers=headers,
        params={'subjectId': subject_id},
        timeout=10
    )
    
    if resp.status_code != 200:
        logger.error(f"Detail failed: {resp.status_code} - {resp.text[:200]}")
        return None
    
    return resp.json()


def get_stream_data(session, headers, subject_id, detail_path, season=1, episode=1):
    """Get streaming/download URLs for a movie."""
    resp = session.get(
        f'{API_BASE}/wefeed-h5api-bff/subject/play',
        headers=headers,
        params={
            'subjectId': subject_id,
            'se': season,
            'ep': episode,
            'detailPath': detail_path,
            'streamSignType': 0
        },
        timeout=10
    )
    
    if resp.status_code != 200:
        logger.error(f"Stream failed: {resp.status_code} - {resp.text[:200]}")
        return None
    
    return resp.json()


def get_download_data(session, headers, subject_id):
    """Get download URLs for a movie."""
    resp = session.get(
        f'{API_BASE}/wefeed-h5api-bff/subject/download',
        headers=headers,
        params={'subjectId': subject_id},
        timeout=10
    )
    
    if resp.status_code != 200:
        logger.error(f"Download failed: {resp.status_code} - {resp.text[:200]}")
        return None
    
    return resp.json()


# ============================================================
# API ROUTES
# ============================================================

@app.route('/recherche', methods=['GET'])
def recherche():
    """
    Search for movies.
    
    Query params:
        film (required): Search keyword (e.g., "Jackie Chan")
        uid  (required): User ID for caching results
    
    Returns JSON array of movies with title, image URL, and index.
    """
    film = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    
    if not film:
        return jsonify({"error": "Paramètre 'film' requis. Ex: /recherche?film=Jackie+Chan&uid=123"}), 400
    if not uid:
        return jsonify({"error": "Paramètre 'uid' requis. Ex: /recherche?film=Jackie+Chan&uid=123"}), 400
    
    logger.info(f"Search: film='{film}', uid={uid}")
    
    # Authenticate
    session, headers = create_authenticated_session()
    
    # Search
    result = search_movies(session, headers, film)
    
    if not result or result.get('code') != 0:
        return jsonify({
            "error": "Erreur lors de la recherche",
            "details": result.get('message', 'Unknown error') if result else 'No response'
        }), 500
    
    items = result.get('data', {}).get('items', [])
    
    if not items:
        return jsonify({
            "message": "Aucun résultat trouvé",
            "results": []
        }), 200
    
    # Format results
    formatted = []
    cache_entry = []
    
    for i, item in enumerate(items):
        movie = {
            "index": i + 1,
            "title": item.get('title', 'Inconnu'),
            "cover_url": item.get('cover', {}).get('url', ''),
            "subjectId": item.get('subjectId', ''),
            "detailPath": item.get('detailPath', ''),
            "genre": item.get('genre', ''),
            "releaseDate": item.get('releaseDate', ''),
            "imdbRating": item.get('imdbRatingValue', ''),
            "hasResource": item.get('hasResource', False),
            "subjectType": "Film" if item.get('subjectType') == 1 else "Série" if item.get('subjectType') == 2 else "Autre",
            "description": item.get('description', ''),
        }
        formatted.append(movie)
        cache_entry.append({
            "index": i + 1,
            "subjectId": item.get('subjectId', ''),
            "detailPath": item.get('detailPath', ''),
            "title": item.get('title', ''),
        })
    
    # Cache results for this user
    search_cache[uid] = {
        "results": cache_entry,
        "total": result.get('data', {}).get('pager', {}).get('totalCount', 0),
        "timestamp": time.time()
    }
    save_cache()
    
    return jsonify({
        "message": f"{len(formatted)} résultats trouvés",
        "total": result.get('data', {}).get('pager', {}).get('totalCount', 0),
        "results": formatted
    }), 200


@app.route('/stream', methods=['GET'])
def stream():
    """
    Get streaming/download URL for a movie by its search result index.
    
    Query params:
        film (required): Index from search results (1, 2, 3, ...)
        uid  (required): User ID to retrieve cached search results
    
    Returns streaming/download URLs for the movie.
    """
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    
    if not film_index:
        return jsonify({"error": "Paramètre 'film' requis. Ex: /stream?film=1&uid=123"}), 400
    if not uid:
        return jsonify({"error": "Paramètre 'uid' requis. Ex: /stream?film=1&uid=123"}), 400
    
    try:
        film_index = int(film_index)
    except ValueError:
        return jsonify({"error": "'film' doit être un nombre (1, 2, 3...)"}), 400
    
    # Check cache
    if uid not in search_cache:
        return jsonify({
            "error": "Aucune recherche en cache. Faites d'abord /recherche?film=...&uid=" + uid
        }), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({
            "error": f"Index invalide. Choisissez entre 1 et {len(cached)}"
        }), 400
    
    movie = cached[film_index - 1]
    logger.info(f"Stream request: uid={uid}, index={film_index}, movie={movie['title']}")
    
    # Authenticate
    session, headers = create_authenticated_session()
    
    # Get stream data
    stream_data = get_stream_data(
        session, headers,
        movie['subjectId'],
        movie['detailPath']
    )
    
    # Get download data
    download_data = get_download_data(
        session, headers,
        movie['subjectId']
    )
    
    # Get full detail
    detail_data = get_movie_detail(
        session, headers,
        movie['subjectId']
    )
    
    response = {
        "title": movie['title'],
        "index": film_index,
        "streams": [],
        "downloads": [],
        "detail": {},
    }
    
    # Parse stream data
    if stream_data and stream_data.get('code') == 0:
        data = stream_data.get('data', {})
        streams = data.get('streams', [])
        for s in streams:
            response['streams'].append({
                "quality": s.get('quality', ''),
                "url": s.get('url', ''),
                "format": s.get('format', ''),
                "size": s.get('size', 0),
            })
        response['hls'] = data.get('hls', [])
        response['dash'] = data.get('dash', [])
        response['vipLocked'] = data.get('vipLocked', False)
        response['freeNum'] = data.get('freeNum', 0)
    
    # Parse download data
    if download_data and download_data.get('code') == 0:
        data = download_data.get('data', {})
        downloads = data.get('downloads', [])
        for d in downloads:
            response['downloads'].append({
                "quality": d.get('quality', ''),
                "url": d.get('url', ''),
                "format": d.get('format', ''),
                "size": d.get('size', 0),
            })
    
    # Parse detail data
    if detail_data and detail_data.get('code') == 0:
        subject = detail_data.get('data', {}).get('subject', {})
        response['detail'] = {
            "title": subject.get('title', ''),
            "description": subject.get('description', ''),
            "releaseDate": subject.get('releaseDate', ''),
            "duration": subject.get('duration', 0),
            "genre": subject.get('genre', ''),
            "country": subject.get('countryName', ''),
            "imdbRating": subject.get('imdbRatingValue', ''),
            "cover_url": subject.get('cover', {}).get('url', ''),
        }
    
    # Also provide direct download link format from MovieBox
    # The site constructs: /wefeed-h5api-bff/subject/download?subjectId=X
    response['direct_download_url'] = f"{API_BASE}/wefeed-h5api-bff/subject/download?subjectId={movie['subjectId']}"
    
    return jsonify(response), 200


@app.route('/detail', methods=['GET'])
def detail():
    """
    Get detailed info about a movie by its search result index.
    
    Query params:
        film (required): Index from search results (1, 2, 3, ...)
        uid  (required): User ID to retrieve cached search results
    """
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    
    if not film_index:
        return jsonify({"error": "Paramètre 'film' requis. Ex: /detail?film=1&uid=123"}), 400
    if not uid:
        return jsonify({"error": "Paramètre 'uid' requis. Ex: /detail?film=1&uid=123"}), 400
    
    try:
        film_index = int(film_index)
    except ValueError:
        return jsonify({"error": "'film' doit être un nombre (1, 2, 3...)"}), 400
    
    if uid not in search_cache:
        return jsonify({
            "error": "Aucune recherche en cache. Faites d'abord /recherche?film=...&uid=" + uid
        }), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({
            "error": f"Index invalide. Choisissez entre 1 et {len(cached)}"
        }), 400
    
    movie = cached[film_index - 1]
    logger.info(f"Detail request: uid={uid}, index={film_index}, movie={movie['title']}")
    
    session, headers = create_authenticated_session()
    detail_data = get_movie_detail(session, headers, movie['subjectId'])
    
    if not detail_data or detail_data.get('code') != 0:
        return jsonify({"error": "Impossible d'obtenir les détails"}), 500
    
    subject = detail_data.get('data', {}).get('subject', {})
    
    return jsonify({
        "title": subject.get('title', ''),
        "description": subject.get('description', ''),
        "releaseDate": subject.get('releaseDate', ''),
        "duration_seconds": subject.get('duration', 0),
        "duration_minutes": round(subject.get('duration', 0) / 60, 1),
        "genre": subject.get('genre', ''),
        "country": subject.get('countryName', ''),
        "imdbRating": subject.get('imdbRatingValue', ''),
        "imdbRatingCount": subject.get('imdbRatingCount', ''),
        "cover_url": subject.get('cover', {}).get('url', ''),
        "still_images": [s.get('url', '') for s in (subject.get('stills') or [])],
        "staff": [
            {"name": s.get('name', ''), "role": s.get('role', '')}
            for s in (subject.get('staffList') or [])
        ],
        "subtitles": subject.get('subtitles', ''),
        "trailer": (subject.get('trailer') or {}).get('url', ''),
        "dubs": subject.get('dubs', ''),
        "subjectType": "Film" if subject.get('subjectType') == 1 else "Série",
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "MovieBox API",
        "cached_users": len(search_cache),
        "version": "1.0.0"
    }), 200


@app.route('/', methods=['GET'])
def index():
    """API documentation."""
    return jsonify({
        "name": "MovieBox API",
        "version": "1.0.0",
        "description": "API REST pour rechercher et télécharger des films depuis themoviebox.xyz",
        "endpoints": {
            "GET /recherche": {
                "params": "?film=<query>&uid=<user_id>",
                "description": "Rechercher des films/séries",
                "example": "/recherche?film=Jackie+Chan&uid=123"
            },
            "GET /stream": {
                "params": "?film=<index>&uid=<user_id>",
                "description": "Obtenir les URLs de streaming/téléchargement par index",
                "example": "/stream?film=1&uid=123"
            },
            "GET /detail": {
                "params": "?film=<index>&uid=<user_id>",
                "description": "Obtenir les détails complets d'un film par index",
                "example": "/detail?film=1&uid=123"
            },
            "GET /health": {
                "description": "Vérifier l'état du service"
            }
        },
        "workflow": [
            "1. GET /recherche?film=Jackie+Chan&uid=monTel → retourne les résultats avec index",
            "2. GET /stream?film=1&uid=monTel → retourne les URLs de streaming pour le résultat #1",
            "3. GET /stream?film=2&uid=monTel → streaming pour le résultat #2, etc."
        ]
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Démarrage du serveur MovieBox API sur le port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
