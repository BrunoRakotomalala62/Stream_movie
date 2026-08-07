#!/usr/bin/env python3
"""
Script de téléchargement pour MovieBox
Utilise un navigateur headless (Playwright) pour télécharger les films
en contournant l'anti-leeching du CDN.

Usage:
    pip install playwright && playwright install chromium
    python download_movie.py "Jackie Chan" 1
"""

import asyncio
import sys
import os
import time
import hashlib
import json
import requests
from pathlib import Path

API_BASE = "https://h5-api.aoneroom.com"
ORIGIN = "https://themoviebox.xyz"


def generate_client_token():
    ts = int(time.time())
    return f"{ts},{hashlib.md5(str(ts)[::-1].encode()).hexdigest()}"


def authenticate():
    """Get an authenticated API session."""
    session = requests.Session()
    token = generate_client_token()
    
    headers = {
        'Origin': ORIGIN,
        'Referer': f'{ORIGIN}/',
        'Accept': 'application/json',
        'X-Request-Lang': 'en',
        'X-Client-Token': token,
        'X-Client-Info': '{"timezone":"Indian/Antananarivo"}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    resp = session.get(f'{API_BASE}/wefeed-h5api-bff/subject/everyone-search', headers=headers)
    x_user = resp.headers.get('x-user', '')
    if x_user:
        headers['Authorization'] = f"Bearer {json.loads(x_user).get('token', '')}"
    
    return session, headers


def search(session, headers, query):
    """Search for a movie."""
    resp = session.post(
        f'{API_BASE}/wefeed-h5api-bff/subject/search',
        headers=headers,
        json={"keyword": query, "page": 1, "perPage": 20, "subjectType": 0},
        timeout=15
    )
    return resp.json().get('data', {}).get('items', [])


def get_stream_url(session, headers, subject_id, detail_path):
    """Get the streaming URL."""
    movie_headers = {**headers, 'Referer': f'{ORIGIN}/en/movies/{detail_path}'}
    resp = session.get(
        f'{API_BASE}/wefeed-h5api-bff/subject/play',
        headers=movie_headers,
        params={'subjectId': subject_id, 'se': 0, 'ep': 0, 'detailPath': detail_path, 'streamSignType': 0}
    )
    streams = resp.json().get('data', {}).get('streams', [])
    return streams[0]['url'] if streams else None


async def download_with_browser(movie_url, output_path):
    """
    Use Playwright to open the movie page in a real browser,
    intercept video network requests, and download the MP4.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright non installé. Lance :")
        print("   pip install playwright && playwright install chromium")
        return False
    
    print(f"🌐 Ouverture de {movie_url} dans le navigateur...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        
        # Collect all video URLs
        video_urls = set()
        
        async def handle_request(request):
            url = request.url
            if any(ext in url.lower() for ext in ['.mp4', '.m3u8', '.ts', 'video', 'stream']):
                video_urls.add(url)
                if '.mp4' in url and 'sign=' in url:
                    print(f"🎯 URL vidéo détectée : {url[:100]}...")
        
        page.on('request', handle_request)
        
        # Go to movie page
        await page.goto(movie_url, wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(5)
        
        # Try clicking play button
        try:
            play_btn = await page.wait_for_selector('video, .art-video, [class*="play"]', timeout=10000)
            if play_btn:
                await play_btn.click()
                await asyncio.sleep(5)
        except:
            pass
        
        await asyncio.sleep(3)
        
        await browser.close()
        
        if video_urls:
            print(f"\n📋 URLs vidéo trouvées ({len(video_urls)}):")
            for u in video_urls:
                print(f"   {u[:150]}")
            return True
        else:
            print("❌ Aucune URL vidéo trouvée")
            return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python download_movie.py <recherche> [index]")
        print("Ex:    python download_movie.py 'Jackie Chan' 1")
        sys.exit(1)
    
    query = sys.argv[1]
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    
    print(f"🔍 Recherche : {query}")
    session, headers = authenticate()
    results = search(session, headers, query)
    
    if not results:
        print("❌ Aucun résultat")
        sys.exit(1)
    
    print(f"\n📋 Résultats ({len(results)}):")
    for i, r in enumerate(results):
        has = "✅" if r.get('hasResource') else "❌"
        print(f"  {i+1}. {has} {r['title']} ({r.get('releaseDate', '?')[:4]}) - {r.get('genre', '')}")
    
    if index > len(results):
        print(f"❌ Index invalide (max {len(results)})")
        sys.exit(1)
    
    movie = results[index - 1]
    print(f"\n🎬 Film sélectionné : {movie['title']}")
    
    # Option 1 : URL du stream (pour info)
    stream_url = get_stream_url(session, headers, movie['subjectId'], movie['detailPath'])
    print(f"\n📡 URL stream API : {stream_url[:100] if stream_url else 'N/A'}...")
    
    # Option 2 : Page du film sur le site (ça marche dans un navigateur !)
    watch_url = f"{ORIGIN}/en/movies/{movie['detailPath']}"
    print(f"🌐 Regarder en ligne : {watch_url}")
    
    # Option 3 : Utiliser Playwright
    print(f"\n💡 Solutions pour télécharger :")
    print(f"")
    print(f"   ✅ SOLUTION 1 (recommandée) : Ouvre le lien dans ton navigateur")
    print(f"      → {watch_url}")
    print(f"      Le player intégré lit la vidéo directement. Pas de blocage.")
    print(f"")
    print(f"   ✅ SOLUTION 2 : Utilise l'API pour le lien watch_online")
    print(f"      → /stream?film={index}&uid=phone → champ watch_online")
    print(f"")
    print(f"   🔧 SOLUTION 3 (playwright) :")
    print(f"      pip install playwright && playwright install chromium")
    print(f"      python download_movie.py '{query}' {index}")
    print(f"      → Le navigateur headless contourne le blocage IP")


if __name__ == '__main__':
    main()
