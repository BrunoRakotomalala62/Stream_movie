"""
Multi-Site Movie Scraper
Support: MovieBox, French-Stream.one, VidSrc.fyi
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
    name: str
    origin: str
    requires_auth: bool = False
    
    @abstractmethod
    def search(self, query: str, page: int = 1) -> list[dict]:
        pass
    
    @abstractmethod
    def get_stream_url(self, movie: dict) -> dict:
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
        
        resp = self.session.get(f'{self.api_base}/wefeed-h5api-bff/subject/play', headers=headers,
            params={'subjectId': movie['id'], 'se': 0, 'ep': 0, 'detailPath': movie['detailPath'], 'streamSignType': 0}, timeout=10)
        if resp.status_code == 200:
            for s in resp.json().get('data', {}).get('streams', []):
                streams.append({"url": s.get('url', ''), "resolution": s.get('resolutions', '?'), "size_mb": round(int(s.get('size', 0)) / 1048576, 1)})
        
        resp = self.session.get(f'{self.api_base}/wefeed-h5api-bff/subject/download', headers=headers,
            params={'subjectId': movie['id']}, timeout=10)
        if resp.status_code == 200:
            for d in resp.json().get('data', {}).get('downloads', []):
                downloads.append({"url": d.get('url', ''), "resolution": d.get('resolution', '?'), "size_mb": round(int(d.get('size', 0)) / 1048576, 1)})
        
        return {"streams": streams, "downloads": downloads, "note": "CDN bloque les IPs serveur. Utilise watch_url pour player integre."}


# ============================================================
# 2. FRENCH-STREAM.ONE SCRAPER
# ============================================================

class FrenchStreamOneScraper(BaseScraper):
    name = "French-Stream.one"
    origin = "https://french-stream.one"
    requires_auth = False
    
    def __init__(self):
        self.session = requests.Session()
    
    def search(self, query, page=1):
        """POST /engine/ajax/search.php → HTML structuré."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': self.origin,
        }
        
        resp = self.session.post(f'{self.origin}/engine/ajax/search.php',
            headers=headers,
            data=f'query={requests.utils.quote(query)}&page={page}',
            timeout=15)
        
        if resp.status_code != 200:
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        
        for item in soup.select('.search-item'):
            onclick = item.get('onclick', '')
            link_match = re.search(r"location\.href='([^']+)'", onclick)
            href = link_match.group(1) if link_match else ''
            
            img_el = item.select_one('img[src]')
            title_el = item.select_one('.search-title')
            
            img = img_el.get('src', '') if img_el else ''
            title_raw = title_el.get_text(strip=True) if title_el else ''
            
            year_match = re.search(r'\((\d{4})\)', title_raw)
            title = re.sub(r'\s*\(\d{4}\)', '', title_raw).strip()
            year = year_match.group(1) if year_match else ''
            
            if title:
                full_url = href if href.startswith('http') else f"{self.origin}{href}"
                results.append({
                    "title": title, "year": year, "cover_url": img,
                    "detail_url": full_url, "href": href, "site": self.name,
                })
        return results
    
    def get_stream_url(self, movie):
        url = movie.get('detail_url', f"{self.origin}{movie.get('href', '')}")
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': self.origin}
        resp = self.session.get(url, headers=headers, timeout=15)
        html = resp.text
        
        iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', html)
        
        ld_json = re.findall(r'<script type="application/ld\+json">([^<]+)</script>', html)
        metadata = {}
        if ld_json:
            try:
                data = json.loads(ld_json[0])
                if isinstance(data, list) and len(data) > 0:
                    m = data[0]
                    metadata = {"name": m.get('name', ''), "description": m.get('description', ''),
                               "image": m.get('image', ''), "rating": m.get('aggregateRating', {}).get('ratingValue', '')}
            except: pass
        
        return {"streams": [], "downloads": [], "iframes": iframes, "metadata": metadata,
                "watch_url": url, "note": "Player charge dynamiquement (wprog.js). Ouvre watch_url dans le navigateur."}


# ============================================================
# 3. VIDSRC.FYI SCRAPER
# ============================================================

class VidSrcScraper(BaseScraper):
    name = "VidSrc.fyi"
    origin = "https://vidsrc.fyi"
    requires_auth = False
    
    def search(self, query, page=1):
        results = []
        try:
            resp = requests.get(f'{self.origin}/vapi/movie/new', timeout=10, headers={'Accept': 'application/json'})
            if resp.status_code == 200:
                for item in resp.json().get('result', [])[:20]:
                    imdb_id = item.get('imdb_id', '')
                    results.append({"title": imdb_id, "id": imdb_id, "embed_url": f"{self.origin}/embed/movie/{imdb_id}", "site": self.name})
        except: pass
        return results
    
    def get_stream_url(self, movie):
        imdb_id = movie.get('id', '')
        return {"streams": [], "embed_url": f"{self.origin}/embed/movie/{imdb_id}",
                "note": "Ajoute embed_url dans un <iframe>. Aucun blocage IP."}


# ============================================================
# REGISTRY
# ============================================================

SCRAPERS: dict[str, BaseScraper] = {
    'moviebox': MovieBoxScraper(),
    'frenchstream': FrenchStreamOneScraper(),
    'vidsrc': VidSrcScraper(),
}


def search_all(query: str, sites: list[str] = None) -> dict:
    if sites is None:
        sites = list(SCRAPERS.keys())
    
    all_results = {}
    for site_name in sites:
        scraper = SCRAPERS.get(site_name)
        if not scraper:
            continue
        try:
            results = scraper.search(query)
            all_results[site_name] = {"name": scraper.name, "count": len(results), "results": results}
        except Exception as e:
            logger.error(f"Error {site_name}: {e}")
            all_results[site_name] = {"name": scraper.name, "count": 0, "results": [], "error": str(e)}
    return all_results


def get_stream(site: str, movie_data: dict) -> dict:
    scraper = SCRAPERS.get(site)
    if not scraper:
        return {"error": f"Site '{site}' non supporte"}
    return scraper.get_stream_url(movie_data)
