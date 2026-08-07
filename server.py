"""
MovieBox API Server
API REST pour rechercher des films et obtenir des liens

⚠️ IMPORTANT: Le CDN (hakunaymatata.com) bloque les IPs de serveurs.
Pour visionner un film, utilise /watch qui redirige vers le player MovieBox.
"""

import hashlib
import time
import json
import os
import logging
from flask import Flask, request, jsonify, redirect
import requests

app = Flask(__name__)

API_BASE = "https://h5-api.aoneroom.com"
ORIGIN = "https://themoviebox.xyz"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
RESULTS_CACHE_FILE = os.path.join(CACHE_DIR, "search_results.json")

search_cache = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

os.makedirs(CACHE_DIR, exist_ok=True)

try:
    if os.path.exists(RESULTS_CACHE_FILE):
        with open(RESULTS_CACHE_FILE, 'r') as f:
            search_cache = json.load(f)
except: pass

def save_cache():
    try:
        with open(RESULTS_CACHE_FILE, 'w') as f:
            json.dump(search_cache, f)
    except: pass

def generate_client_token():
    ts = int(time.time())
    rev = str(ts)[::-1]
    md5_hash = hashlib.md5(rev.encode()).hexdigest()
    return f"{ts},{md5_hash}"

def create_authenticated_session(detail_path=None):
    session = requests.Session()
    token = generate_client_token()
    referer_url = f'{ORIGIN}/en/movies/{detail_path}' if detail_path else f'{ORIGIN}/'
    
    headers = {
        'Origin': ORIGIN, 'Referer': referer_url,
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'X-Request-Lang': 'en', 'X-Client-Token': token,
        'X-Client-Info': '{"timezone":"Indian/Antananarivo"}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        resp = session.get(f'{API_BASE}/wefeed-h5api-bff/subject/everyone-search', headers=headers, timeout=10)
        if resp.status_code == 200:
            x_user = resp.headers.get('x-user', '')
            if x_user:
                headers['Authorization'] = f"Bearer {json.loads(x_user).get('token', '')}"
    except: pass
    
    return session, headers

def search_movies(session, headers, keyword, page=1, per_page=20):
    data = {"keyword": keyword, "page": page, "perPage": per_page, "subjectType": 0}
    resp = session.post(f'{API_BASE}/wefeed-h5api-bff/subject/search', headers=headers, json=data, timeout=15)
    return resp.json() if resp.status_code == 200 else None

def get_movie_detail(session, headers, subject_id):
    resp = session.get(f'{API_BASE}/wefeed-h5api-bff/detail', headers=headers, params={'subjectId': subject_id}, timeout=10)
    return resp.json() if resp.status_code == 200 else None

def get_stream_urls(session, headers, subject_id, detail_path):
    """Get stream/download URLs from the API."""
    result = {"streams": [], "downloads": []}
    
    resp = session.get(f'{API_BASE}/wefeed-h5api-bff/subject/play', headers=headers,
                       params={'subjectId': subject_id, 'se': 0, 'ep': 0, 'detailPath': detail_path, 'streamSignType': 0}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get('code') == 0:
            for s in data.get('data', {}).get('streams', []):
                result['streams'].append({'url': s.get('url', ''), 'resolution': s.get('resolutions', '?'), 'size_bytes': int(s.get('size', 0))})
    
    resp = session.get(f'{API_BASE}/wefeed-h5api-bff/subject/download', headers=headers,
                       params={'subjectId': subject_id}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get('code') == 0:
            for d in data.get('data', {}).get('downloads', []):
                result['downloads'].append({'url': d.get('url', ''), 'resolution': d.get('resolution', '?'), 'size_bytes': int(d.get('size', 0))})
    
    return result


# ============================================================
# ROUTES
# ============================================================

@app.route('/recherche', methods=['GET'])
def recherche():
    film = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    if not film: return jsonify({"error": "Parametre 'film' requis"}), 400
    if not uid: return jsonify({"error": "Parametre 'uid' requis"}), 400
    
    session, headers = create_authenticated_session()
    result = search_movies(session, headers, film)
    
    if not result or result.get('code') != 0:
        return jsonify({"error": "Erreur recherche", "details": result.get('message', '') if result else ''}), 500
    
    items = result.get('data', {}).get('items', [])
    if not items:
        return jsonify({"message": "Aucun resultat", "results": []}), 200
    
    formatted, cache_entry = [], []
    for i, item in enumerate(items):
        movie = {
            "index": i + 1, "title": item.get('title', ''),
            "cover_url": item.get('cover', {}).get('url', ''),
            "genre": item.get('genre', ''), "releaseDate": item.get('releaseDate', ''),
            "imdbRating": item.get('imdbRatingValue', ''),
            "type": "Film" if item.get('subjectType') == 1 else "Serie",
            "hasResource": item.get('hasResource', False),
        }
        formatted.append(movie)
        cache_entry.append({
            "index": i + 1, "subjectId": item.get('subjectId', ''),
            "detailPath": item.get('detailPath', ''), "title": item.get('title', ''),
        })
    
    search_cache[uid] = {"results": cache_entry, "total": result.get('data', {}).get('pager', {}).get('totalCount', 0), "timestamp": time.time()}
    save_cache()
    
    return jsonify({"message": f"{len(formatted)} resultats", "total": search_cache[uid]['total'], "results": formatted}), 200


@app.route('/watch', methods=['GET'])
def watch():
    """Redirige vers le player MovieBox pour visionner le film."""
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    if not film_index or not uid:
        return jsonify({"error": "Parametres 'film' et 'uid' requis"}), 400
    try: film_index = int(film_index)
    except: return jsonify({"error": "'film' doit etre un nombre"}), 400
    
    if uid not in search_cache:
        return jsonify({"error": "Faites /recherche d'abord"}), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({"error": f"Index 1-{len(cached)}"}), 400
    
    movie = cached[film_index - 1]
    return redirect(f"{ORIGIN}/en/movies/{movie['detailPath']}", code=302)


@app.route('/stream', methods=['GET'])
def stream():
    """Retourne les URLs de streaming + metadata."""
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    if not film_index or not uid:
        return jsonify({"error": "Parametres requis"}), 400
    try: film_index = int(film_index)
    except: return jsonify({"error": "Nombre requis"}), 400
    
    if uid not in search_cache:
        return jsonify({"error": "Faites /recherche d'abord"}), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached):
        return jsonify({"error": f"Index 1-{len(cached)}"}), 400
    
    movie = cached[film_index - 1]
    
    session, headers = create_authenticated_session(movie['detailPath'])
    headers['Referer'] = f"{ORIGIN}/en/movies/{movie['detailPath']}"
    
    urls = get_stream_urls(session, headers, movie['subjectId'], movie['detailPath'])
    detail = get_movie_detail(session, headers, movie['subjectId'])
    
    response = {
        "title": movie['title'], "index": film_index,
        "watch_url": f"{ORIGIN}/en/movies/{movie['detailPath']}",
        "watch_endpoint": f"/watch?film={film_index}&uid={uid}",
        "streams": urls['streams'],
        "downloads": urls['downloads'],
        "note": "Les URLs CDN peuvent etre bloquees. Utilise /watch pour visionner."
    }
    
    if detail and detail.get('code') == 0:
        s = detail.get('data', {}).get('subject', {})
        response['detail'] = {
            "title": s.get('title', ''), "description": s.get('description', ''),
            "releaseDate": s.get('releaseDate', ''), "duration_min": round(s.get('duration', 0) / 60, 1),
            "genre": s.get('genre', ''), "country": s.get('countryName', ''),
            "imdbRating": s.get('imdbRatingValue', ''), "cover_url": s.get('cover', {}).get('url', ''),
        }
    
    return jsonify(response), 200


@app.route('/detail', methods=['GET'])
def detail():
    film_index = request.args.get('film', '').strip()
    uid = request.args.get('uid', '').strip()
    if not film_index or not uid: return jsonify({"error": "Parametres requis"}), 400
    try: film_index = int(film_index)
    except: return jsonify({"error": "Nombre requis"}), 400
    
    if uid not in search_cache: return jsonify({"error": "Faites /recherche d'abord"}), 404
    
    cached = search_cache[uid]['results']
    if film_index < 1 or film_index > len(cached): return jsonify({"error": f"Index 1-{len(cached)}"}), 400
    
    movie = cached[film_index - 1]
    session, headers = create_authenticated_session(movie['detailPath'])
    headers['Referer'] = f"{ORIGIN}/en/movies/{movie['detailPath']}"
    
    data = get_movie_detail(session, headers, movie['subjectId'])
    if not data or data.get('code') != 0: return jsonify({"error": "Detail indisponible"}), 500
    
    s = data.get('data', {}).get('subject', {})
    return jsonify({
        "title": s.get('title', ''), "description": s.get('description', ''),
        "releaseDate": s.get('releaseDate', ''), "duration_min": round(s.get('duration', 0) / 60, 1),
        "genre": s.get('genre', ''), "country": s.get('countryName', ''),
        "imdbRating": s.get('imdbRatingValue', ''), "cover_url": s.get('cover', {}).get('url', ''),
        "watch_url": f"{ORIGIN}/en/movies/{movie['detailPath']}",
        "staff": [{"name": x.get('name', ''), "role": x.get('role', '')} for x in (s.get('staffList') or [])],
        "trailer_url": (s.get('trailer') or {}).get('url', ''),
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "MovieBox API", "version": "2.0.0"}), 200


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "name": "MovieBox API", "version": "2.0.0",
        "description": "API pour rechercher et visionner des films depuis themoviebox.xyz",
        "workflow": [
            "1. GET /recherche?film=Jackie+Chan&uid=123 => liste des films",
            "2. GET /stream?film=1&uid=123 => URLs + metadonnees",
            "3. GET /watch?film=1&uid=123 => ouvre le player dans le navigateur",
            "4. GET /detail?film=1&uid=123 => details complets"
        ],
        "note": "Pour telecharger, utilise /watch sur ton telephone (le player integre gere tout)."
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"MovieBox API sur le port {port}")
    app.run(host='0.0.0.0', port=port)
