"""
MovieBox API Server - Flask REST API
Scrapes themoviebox.xyz to search and download movies
Routes:
  GET /recherche?film=<query>&uid=<user_id>  - Search movies
  GET /stream?film=<index>&uid=<user_id>     - Get download/stream URL
  GET /detail?film=<index>&uid=<user_id>     - Get movie details
  GET /download?film=<index>&uid=<user_id>   - Proxy download (server streams MP4)
"""

import hashlib
import time
import json
import os
import logging
from flask import Flask, request, jsonify, Response, stream_with_context
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


def create_authenticated_session(detail_path=None):
    """Create an authenticated session with the MovieBox API.
    
    The flow:
    1. Generate a client token
    2. Make a GET request to everyone-search to obtain a cookie token
    3. Use the cookie token for subsequent POST requests
    
    Args:
        detail_path: Optional detail path to use as Referer (e.g., 'the-young-master-yHzyTiIxYF')
    
    IMPORTANT: Le Referer doit pointer vers la page du film pour que
    les endpoints play/download renvoient les vraies URLs de streaming.
    Sans ca, l'API retourne des streams/downloads vides (anti-leeching).
    """
    session = requests.Session()
    
    token = generate_client_token()
    
    # Construire le Referer : page du film si dispo, sinon homepage
    referer_url = f'{ORIGIN}/'
    if detail_path:
        referer_url = f'{ORIGIN}/en/movies/{detail_path}'
    
    headers = {
        'Origin': ORIGIN,
        'Referer': referer_url,
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


def get_fresh_cdn_url(session, headers, movie):
    """Retry getting a fresh CDN URL if the first one expired (sign/token)."""
    try:
        logger.info("Retrying with fresh CDN URL...")
        stream_data = get_stream_data(session, headers, movie['subjectId'], movie['detailPath'])
        if stream_data and stream_data.get('code') == 0:
            streams = stream_data.get('data', {}).get('streams', [])
            if streams:
                return streams[0].get('url')
        
        download_data = get_download_data(session, headers, movie['subjectId'])
        if download_data and download_data.get('code') == 0:
            downloads = download_data.get('data', {}).get('downloads', [])
            if downloads:
                return downloads[0].get('url')
    except Exception as e:
        logger.error(f"Retry failed: {e}")
    return None


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
        return jsonify({"error": "Parametre 'film' requis. Ex: /recherche?film=Jackie+Chan&uid=123"}), 400
    if not uid:
        return jsonify({"error": "Parametre 'uid' requis. Ex: /recherche?film=Jackie+Chan&uid=123"}), 400
    
    logger.info(f"Search: film='{film}', uid={uid}")
    
    # Authenticate (pas besoin de detail_path pour la recherche)
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
            "message": "Aucun resultat trouve",
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
            "subjectType": "Film" if item.get('subjectType') == 1 else "Serie" if item.get('subjectType') == 2 else "Autre",
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
        "message": f"{len(formatted)} resultats trouves",
        "total": result.get('data', {}).get('pager', {}).get('totalCount', 0),
        "results": formatted
    }), 200


@app.route('/stream', methods=['GET'])
def stream():
    """
    Get streaming/download URL for a movie by its search result index.
    Returns URLs + metadata.
    """
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    
    if not film_index or not uid:
        return jsonify({"error": "Parametres 'film' et 'uid' requis"}), 400
    
    try:
        film_index = int(film_index)
    except ValueError:
        return jsonify({"error": "'film' doit etre un nombre"}), 400
    
    if uid not in search_cache:
        return jsonify({"error": "Faites d'abord /recherche?film=...&uid=" + uid}), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({"error": f"Index invalide. Choisissez entre 1 et {len(cached)}"}), 400
    
    movie = cached[film_index - 1]
    logger.info(f"Stream request: uid={uid}, index={film_index}, movie={movie['title']}")
    
    # Authenticate avec le detail_path pour le bon Referer
    session, headers = create_authenticated_session(movie['detailPath'])
    movie_referer = f"{ORIGIN}/en/movies/{movie['detailPath']}"
    headers['Referer'] = movie_referer
    
    stream_data = get_stream_data(session, headers, movie['subjectId'], movie['detailPath'])
    download_data = get_download_data(session, headers, movie['subjectId'])
    detail_data = get_movie_detail(session, headers, movie['subjectId'])
    
    response = {
        "title": movie['title'],
        "index": film_index,
        "streams": [],
        "downloads": [],
        "detail": {},
        "download_endpoint": f"/download?film={film_index}&uid={uid}",
        "watch_online": f"{ORIGIN}/en/movies/{movie['detailPath']}"
    }
    
    if stream_data and stream_data.get('code') == 0:
        data = stream_data.get('data', {})
        for s in data.get('streams', []):
            response['streams'].append({
                "url": s.get('url', ''),
                "format": s.get('format', 'MP4'),
                "resolution": s.get('resolutions', '?'),
                "size": s.get('size', 0),
                "size_mb": round(int(s.get('size', 0)) / 1048576, 1),
            })
        response['hls'] = data.get('hls', [])
        response['dash'] = data.get('dash', [])
    
    if download_data and download_data.get('code') == 0:
        for d in download_data.get('data', {}).get('downloads', []):
            response['downloads'].append({
                "url": d.get('url', ''),
                "format": d.get('format', 'MP4'),
                "resolution": d.get('resolution', '?'),
                "size": d.get('size', 0),
                "size_mb": round(int(d.get('size', 0)) / 1048576, 1),
            })
    
    if detail_data and detail_data.get('code') == 0:
        s = detail_data.get('data', {}).get('subject', {})
        response['detail'] = {
            "title": s.get('title', ''),
            "description": s.get('description', ''),
            "releaseDate": s.get('releaseDate', ''),
            "duration": s.get('duration', 0),
            "genre": s.get('genre', ''),
            "country": s.get('countryName', ''),
            "imdbRating": s.get('imdbRatingValue', ''),
            "cover_url": s.get('cover', {}).get('url', ''),
        }
    
    # Best direct URL
    best_url = None
    if response['streams']:
        best_url = response['streams'][0].get('url')
    elif response['downloads']:
        best_url = response['downloads'][0].get('url')
    response['direct_url'] = best_url
    response['message'] = "URL obtenue" if best_url else "Aucune URL directe"
    
    return jsonify(response), 200


@app.route('/download', methods=['GET'])
def download():
    """
    PROXY DOWNLOAD: Le serveur telecharge le fichier depuis le CDN
    et le stream directement au client.
    
    Cela contourne le blocage 403/429 du CDN car la requete
    vient du serveur (Render) avec les bons headers.
    
    Si le CDN bloque quand meme, renvoie un fallback avec le lien
    watch_online pour visionner dans le navigateur.
    """
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    
    if not film_index or not uid:
        return jsonify({"error": "Parametres 'film' et 'uid' requis"}), 400
    
    try:
        film_index = int(film_index)
    except ValueError:
        return jsonify({"error": "'film' doit etre un nombre"}), 400
    
    if uid not in search_cache:
        return jsonify({"error": "Faites d'abord /recherche"}), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({"error": f"Index invalide (1-{len(cached)})"}), 400
    
    movie = cached[film_index - 1]
    logger.info(f"Download proxy: uid={uid}, film={movie['title']}")
    
    # Get CDN URL
    session, headers = create_authenticated_session(movie['detailPath'])
    movie_referer = f"{ORIGIN}/en/movies/{movie['detailPath']}"
    headers['Referer'] = movie_referer
    
    stream_data = get_stream_data(session, headers, movie['subjectId'], movie['detailPath'])
    download_data = get_download_data(session, headers, movie['subjectId'])
    
    cdn_url = None
    if stream_data and stream_data.get('code') == 0:
        streams = stream_data.get('data', {}).get('streams', [])
        if streams:
            cdn_url = streams[0].get('url')
    if not cdn_url and download_data and download_data.get('code') == 0:
        downloads = download_data.get('data', {}).get('downloads', [])
        if downloads:
            cdn_url = downloads[0].get('url')
    
    if not cdn_url:
        return jsonify({
            "error": "Aucune URL disponible",
            "watch_online": f"{ORIGIN}/en/movies/{movie['detailPath']}"
        }), 404
    
    logger.info(f"Streaming from CDN: {cdn_url[:80]}...")
    
    # Proxy download: telecharger du CDN et streamer au client
    cdn_headers = {
        'Referer': movie_referer,
        'Origin': ORIGIN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }
    
    try:
        cdn_response = requests.get(cdn_url, headers=cdn_headers, stream=True, timeout=30)
        
        # Retry with fresh URL if blocked
        if cdn_response.status_code in (403, 429):
            logger.warning(f"CDN blocked ({cdn_response.status_code}), retrying...")
            alt_url = get_fresh_cdn_url(session, headers, movie)
            if alt_url and alt_url != cdn_url:
                cdn_response = requests.get(alt_url, headers=cdn_headers, stream=True, timeout=30)
                cdn_url = alt_url
        
        if cdn_response.status_code in (403, 429):
            logger.error(f"CDN persistently blocked ({cdn_response.status_code})")
            return jsonify({
                "error": "CDN bloque cette IP",
                "watch_online": f"{ORIGIN}/en/movies/{movie['detailPath']}",
                "cdn_url": cdn_url
            }), 403
        
        if cdn_response.status_code != 200:
            logger.error(f"CDN error: {cdn_response.status_code}")
            return jsonify({"error": f"CDN error HTTP {cdn_response.status_code}"}), 502
        
        content_type = cdn_response.headers.get('Content-Type', 'video/mp4')
        content_length = cdn_response.headers.get('Content-Length', '0')
        
        safe_title = "".join(c for c in movie['title'] if c.isalnum() or c in ' _-').rstrip()
        filename = f"{safe_title}.mp4"
        
        def generate():
            bytes_sent = 0
            for chunk in cdn_response.iter_content(chunk_size=1048576):
                if chunk:
                    bytes_sent += len(chunk)
                    yield chunk
            logger.info(f"Download complete: {bytes_sent} bytes for {movie['title']}")
        
        response = Response(stream_with_context(generate()), status=200, content_type=content_type)
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Length'] = content_length
        response.headers['X-Film-Title'] = movie['title']
        response.headers['Cache-Control'] = 'no-cache'
        return response
        
    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout CDN"}), 504
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/detail', methods=['GET'])
def detail():
    """Get detailed info about a movie by its search result index."""
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    
    if not film_index or not uid:
        return jsonify({"error": "Parametres 'film' et 'uid' requis"}), 400
    
    try:
        film_index = int(film_index)
    except ValueError:
        return jsonify({"error": "'film' doit etre un nombre"}), 400
    
    if uid not in search_cache:
        return jsonify({"error": "Faites d'abord /recherche?film=...&uid=" + uid}), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({"error": f"Index invalide (1-{len(cached)})"}), 400
    
    movie = cached[film_index - 1]
    
    session, headers = create_authenticated_session(movie['detailPath'])
    headers['Referer'] = f"{ORIGIN}/en/movies/{movie['detailPath']}"
    detail_data = get_movie_detail(session, headers, movie['subjectId'])
    
    if not detail_data or detail_data.get('code') != 0:
        return jsonify({"error": "Impossible d'obtenir les details"}), 500
    
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
        "staff": [{"name": s.get('name', ''), "role": s.get('role', '')} for s in (subject.get('staffList') or [])],
        "subtitles": subject.get('subtitles', ''),
        "trailer": (subject.get('trailer') or {}).get('url', ''),
        "dubs": subject.get('dubs', ''),
        "subjectType": "Film" if subject.get('subjectType') == 1 else "Serie",
        "watch_online": f"{ORIGIN}/en/movies/{movie['detailPath']}",
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "MovieBox API", "version": "2.0.0"}), 200


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "name": "MovieBox API",
        "version": "2.0.0",
        "endpoints": {
            "GET /recherche": "/recherche?film=Jackie+Chan&uid=123",
            "GET /stream": "/stream?film=1&uid=123",
            "GET /download": "/download?film=1&uid=123 (proxy streaming)",
            "GET /detail": "/detail?film=1&uid=123",
            "GET /health": "/health"
        },
        "workflow": [
            "1. GET /recherche?film=...&uid=... => liste avec index",
            "2. GET /download?film=1&uid=... => telechargement direct (proxy)",
            "3. GET /stream?film=1&uid=... => URLs + metadonnees"
        ]
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Demarrage MovieBox API sur le port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
