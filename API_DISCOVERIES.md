# API Discoveries - Sites de Streaming (07/08/2026)

## 1. MovieBox (themoviebox.xyz)
- Search: POST /wefeed-h5api-bff/subject/search (auth: X-Client-Token)
- Stream: GET /wefeed-h5api-bff/subject/play?subjectId=X&streamSignType=0
- Download: GET /wefeed-h5api-bff/subject/download?subjectId=X
- CDN: bcdnxw.hakunaymatata.com — BLOCKS server IPs (403)
- Player works in browser only

## 2. VidSrc.fyi -> vsembed.ru -> cloudorchestranova.com
- Meta API: GET https://data.vidsrcme.ru/api.php?type=movie&imdb=tt2911666
- Stream API: Add &stream_urls -> returns ENCRYPTED stream_urls
- Decrypted client-side by vsdec.js + HLS.js player
- No IP blocking — public API

## 3. French-Stream (french-stream.al)
- Search: GET /?do=search&subaction=search&story=QUERY (DLE)
- Stream: nested iframes (classic DLE pattern)
- No IP blocking

## 4. Blocked sites
- wiflix.art, papadustream.site, darkino.ink, empire-stream.net
- coflix.media, xalaflix.net, filmstreaming.biz, voirfilms.movie

## Best approach
- Embed iframe: https://vidsrc.fyi/embed/movie/TT_ID (no blocking)
- Direct API for metadata: data.vidsrcme.ru/api.php
- MovieBox for rich search + watch_online redirect
