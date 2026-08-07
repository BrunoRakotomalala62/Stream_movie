"""
Multi-Site Movie Scraper
Supporte: MovieBox, French-Stream, et VidSrc.fyi
Chaque site a son propre adaptateur de recherche + streaming.
"""

import requests
import hashlib
import time
import json
import re
import logging
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Interface commune pour tous les scrapers de sites."""
    
    name: str
    origin: str
    requires_auth: bool = False
    
    @abstractmethod
    def search(self, query: str, page: int = 1) -> list[dict]:
        """Recherche et retourne une liste de films."""
        pass
    
    @abstractmethod
    def get_stream_url(self, movie: dict) -> dict:
        """Retourne les URLs de streaming/téléchargement."""
        pass


# ============================================================
# 1. MOVIEBOX SCRAPER
# ============================================================

class MovieBoxScraper(BaseScraper):
    name = "MovieBox"
    origin = "https://themoviebox.xyz"
    api_base = "https://h5-api.aoneroom.com"
    requires_auth = True
    
    def __init__(self):
        self.session = requests.Session()
    
    def _auth(self, detail_path=None):
        ts = int(time.time())
        rev = str(ts)[::-1]
        token = f"{ts},{hashlib.md5(rev.encode()).hexdigest()}"
        
        referer = f'{self.origin}/en/movies/{detail_path}' if detail_path else f'{self.origin}/'
        
        headers = {
            'Origin': self.origin, 'Referer': referer,
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'X-Request-Lang': 'en', 'X-Client-Token': token,
            'X-Client-Info': '{"timezone":"Indian/Antananarivo"}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resp = self.session.get(f'{self.api_base}/wefeed-h5api-bff/subject/everyone-search', headers=headers, timeout=10)
        x_user = resp.headers.get('x-user', '')
        if x_user:
            headers['Authorization'] = f"Bearer {json.loads(x_user).get('token', '')}"
        
        return headers
    
    def search(self, query, page=1):
        headers = self._auth()
        resp = self.session.post(
            f'{self.api_base}/wefeed-h5api-bff/subject/search',
            headers=headers,
            json={"keyword": query, "page": page, "perPage": 20, "subjectType": 0},
            timeout=15
        )
        
        data = resp.json()
        if data.get('code') != 0:
            return []
        
        results = []
        for item in data.get('data', {}).get('items', []):
            results.append({
                "title": item.get('title', ''),
                "id": item.get('subjectId', ''),
                "detailPath": item.get('detailPath', ''),
                "cover_url": item.get('cover', {}).get('url', ''),
                "genre": item.get('genre', ''),
                "releaseDate": item.get('releaseDate', ''),
                "imdbRating": item.get('imdbRatingValue', ''),
                "type": "movie" if item.get('subjectType') == 1 else "series",
                "site": self.name,
                "watch_url": f"{self.origin}/en/movies/{item.get('detailPath', '')}",
            })
        
        return results
    
    def get_stream_url(self, movie):
        headers = self._auth(movie.get('detailPath', ''))
        headers['Referer'] = f"{self.origin}/en/movies/{movie.get('detailPath', '')}"
        
        streams = []
        downloads = []
        
        resp = self.session.get(
            f'{self.api_base}/wefeed-h5api-bff/subject/play',
            headers=headers,
            params={'subjectId': movie['id'], 'se': 0, 'ep': 0, 'detailPath': movie['detailPath'], 'streamSignType': 0},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            for s in data.get('data', {}).get('streams', []):
                streams.append({
                    "url": s.get('url', ''),
                    "resolution": s.get('resolutions', '?'),
                    "size_mb": round(int(s.get('size', 0)) / 1048576, 1),
                })
        
        resp = self.session.get(
            f'{self.api_base}/wefeed-h5api-bff/subject/download',
            headers=headers,
            params={'subjectId': movie['id']},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            for d in data.get('data', {}).get('downloads', []):
                downloads.append({
                    "url": d.get('url', ''),
                    "resolution": d.get('resolution', '?'),
                    "size_mb": round(int(d.get('size', 0)) / 1048576, 1),
                })
        
        return {
            "streams": streams,
            "downloads": downloads,
            "note": "Les URLs CDN peuvent etre bloquees par IP. Utilise watch_url pour le player integre."
        }


# ============================================================
# 2. FRENCH-STREAM SCRAPER
# ============================================================

class FrenchStreamScraper(BaseScraper):
    name = "French-Stream"
    origin = "https://french-stream.al"
    requires_auth = False
    
    def __init__(self):
        self.session = requests.Session()
    
    def search(self, query, page=1):
        """Recherche via l'endpoint DLE (DataLife Engine)."""
        url = f"{self.origin}/?do=search&subaction=search&story={query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml'
        }
        
        resp = self.session.get(url, headers=headers, timeout=15)
        
        if resp.status_code != 200:
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        
        # Pattern 1: shortstory blocks (typique DLE)
        for story in soup.select('.shortstory, .movie-item, article.movie, .card-film'):
            title_el = story.select_one('h2 a, h3 a, .title a, a.title')
            img_el = story.select_one('img[src]')
            link_el = story.select_one('a[href*="/"][href*="-"]')
            
            title = title_el.get_text(strip=True) if title_el else ''
            href = link_el.get('href', '') if link_el else ''
            img_url = img_el.get('src', '') if img_el else ''
            
            if href.startswith(self.origin):
                href = href[len(self.origin):]
            
            match = re.match(r'/(\d+)-(.+)', href)
            if title and match:
                results.append({
                    "title": title,
                    "id": match.group(1),
                    "slug": match.group(2),
                    "cover_url": img_url if img_url.startswith('http') else f"{self.origin}{img_url}" if img_url else '',
                    "detail_url": f"{self.origin}{href}",
                    "site": self.name,
                })
        
        # Pattern 2: liens directs (fallback)
        if not results:
            movie_links = re.findall(r'href="(/\d+-[^"]+)"', resp.text)
            seen = set()
            for link in movie_links:
                if link not in seen and '/season-' not in link and '-full-' not in link:
                    seen.add(link)
                    match = re.match(r'/(\d+)-(.+)', link)
                    if match:
                        results.append({
                            "title": match.group(2).replace('-', ' ').title(),
                            "id": match.group(1),
                            "slug": match.group(2),
                            "cover_url": '',
                            "detail_url": f"{self.origin}{link}",
                            "site": self.name,
                        })
        
        return results[:30]
    
    def get_stream_url(self, movie):
        """Explore la page du film pour trouver les iframes/sources video."""
        url = movie.get('detail_url', f"{self.origin}/{movie['id']}-{movie.get('slug', '')}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': self.origin,
        }
        
        resp = self.session.get(url, headers=headers, timeout=15)
        html = resp.text
        
        iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', html)
        players = re.findall(r'(?:data-url|data-src|data-video)=["\x27]([^"\x27]+)', html)
        m3u8 = re.findall(r'["\x27]([^"\x27]*\.m3u8[^"\x27]*)', html)
        mp4 = re.findall(r'["\x27]([^"\x27]*\.mp4[^"\x27]*)', html)
        stream_links = re.findall(r'(?:lecteur|player|stream|source|serveur)[^<]*<a[^>]*href="([^"]+)"', html, re.I)
        
        return {
            "streams": [],
            "downloads": [],
            "iframes": iframes,
            "players": players,
            "m3u8_urls": m3u8,
            "mp4_urls": mp4,
            "stream_links": stream_links,
            "watch_url": url,
            "note": "French-Stream utilise des iframes integres. Ouvre watch_url dans le navigateur."
        }


# ============================================================
# 3. VIDSRC.FYI SCRAPER (API publique, pas de cle requise)
# ============================================================

class VidSrcScraper(BaseScraper):
    name = "VidSrc.fyi"
    origin = "https://vidsrc.fyi"
    requires_auth = False
    
    def search(self, query, page=1):
        """Retourne les nouveautes (pas de recherche textuelle directe)."""
        results = []
        try:
            resp = requests.get(f'{self.origin}/vapi/movie/new', timeout=10, headers={'Accept': 'application/json'})
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get('result', [])[:20]:
                    imdb_id = item.get('imdb_id', '')
                    tmdb_id = item.get('tmdb_id', '')
                    results.append({
                        "title": imdb_id,
                        "id": imdb_id,
                        "tmdb_id": tmdb_id,
                        "cover_url": f"https://img.ophim.live/uploads/movies/{tmdb_id}-thumb.jpg",
                        "embed_url": f"{self.origin}/embed/movie/{imdb_id}",
                        "site": self.name,
                        "quality": item.get('quality', '?'),
                    })
        except: pass
        return results
    
    def get_stream_url(self, movie):
        imdb_id = movie.get('id', '')
        return {
            "streams": [],
            "embed_url": f"{self.origin}/embed/movie/{imdb_id}",
            "embed_url_tv": f"{self.origin}/embed/tv/{imdb_id}/1/1",
            "note": "Ajoute cet embed_url dans un <iframe> pour le player. Aucun blocage IP."
        }


# ============================================================
# SCRAPER REGISTRY
# ============================================================

SCRAPERS: dict[str, BaseScraper] = {
    'moviebox': MovieBoxScraper(),
    'frenchstream': FrenchStreamScraper(),
    'vidsrc': VidSrcScraper(),
}


def search_all(query: str, sites: list[str] = None) -> dict:
    """Recherche sur tous les sites ou une liste specifique."""
    if sites is None:
        sites = list(SCRAPERS.keys())
    
    all_results = {}
    for site_name in sites:
        scraper = SCRAPERS.get(site_name)
        if not scraper:
            continue
        try:
            results = scraper.search(query)
            all_results[site_name] = {
                "name": scraper.name,
                "count": len(results),
                "results": results,
            }
        except Exception as e:
            logger.error(f"Error searching {site_name}: {e}")
            all_results[site_name] = {"name": scraper.name, "count": 0, "results": [], "error": str(e)}
    
    return all_results


def get_stream(site: str, movie_data: dict) -> dict:
    """Obtient les URLs de streaming pour un film specifique."""
    scraper = SCRAPERS.get(site)
    if not scraper:
        return {"error": f"Site '{site}' non supporte"}
    return scraper.get_stream_url(movie_data)
