# 🎬 MovieBox API

API REST pour rechercher et télécharger des films depuis **themoviebox.xyz**.

## 🚀 Déploiement sur Render.com

### Méthode rapide : Déploiement automatique

1. Push ce projet sur GitHub
2. Sur [Render.com](https://render.com) → **New +** → **Web Service**
3. Connecte ton repo GitHub
4. Render détecte automatiquement le `Dockerfile`
5. Clique **Deploy** — c'est tout !

### Configuration Render recommandée

| Paramètre | Valeur |
|-----------|--------|
| **Runtime** | Docker |
| **Plan** | Free (ou Starter pour plus de perf) |
| **Health Check Path** | `/health` |
| **Auto-Deploy** | Oui (depuis la branche `main`) |

La variable `PORT` est automatiquement fournie par Render (pas besoin de `.env`).

### Variables d'environnement (optionnelles)

Aucune variable requise. Le `Dockerfile` utilise `${PORT:-5000}` qui fonctionne en local comme sur Render.

### Déploiement manuel (CLI)

```bash
# Build local
docker build -t moviebox-api .

# Test local
docker run -p 5000:5000 moviebox-api
curl http://localhost:5000/recherche?film=Jackie+Chan&uid=123

# Push sur une registry (Docker Hub, GitHub Container Registry, etc.)
docker tag moviebox-api tonuser/moviebox-api:latest
docker push tonuser/moviebox-api:latest
```

Sur Render, choisis **Existing Image** et colle l'URL de l'image.

## 🚀 Installation locale

```bash
pip install -r requirements.txt
python server.py
```

Le serveur démarre sur `http://localhost:5000`.

## 📡 Endpoints

### 1. 🔍 Recherche de films
```http
GET /recherche?film=<query>&uid=<user_id>
```

| Paramètre | Requis | Description |
|-----------|--------|-------------|
| `film`    | ✅     | Mot-clé de recherche (ex: "Jackie Chan") |
| `uid`     | ✅     | Identifiant utilisateur pour le cache |

**Exemple :**
```bash
curl "http://localhost:5000/recherche?film=Jackie+Chan&uid=123"
```

**Réponse :**
```json
{
  "message": "14 résultats trouvés",
  "total": 168,
  "results": [
    {
      "index": 1,
      "title": "The Young Master",
      "cover_url": "https://pbcdnw.aoneroom.com/image/2026/01/21/...jpg",
      "subjectId": "568239684535599800",
      "detailPath": "the-young-master-yHzyTiIxYF",
      "genre": "Action,Adventure,Comedy",
      "releaseDate": "1980-02-09",
      "imdbRating": "7.0",
      "hasResource": true,
      "subjectType": "Film",
      "description": ""
    }
  ]
}
```

### 2. 📋 Détails d'un film
```http
GET /detail?film=<index>&uid=<user_id>
```

| Paramètre | Requis | Description |
|-----------|--------|-------------|
| `film`    | ✅     | Index du résultat (1, 2, 3...) |
| `uid`     | ✅     | Même UID que la recherche |

**Exemple :**
```bash
curl "http://localhost:5000/detail?film=1&uid=123"
```

### 3. 📥 Streaming / Téléchargement
```http
GET /stream?film=<index>&uid=<user_id>
```

| Paramètre | Requis | Description |
|-----------|--------|-------------|
| `film`    | ✅     | Index du résultat (1, 2, 3...) |
| `uid`     | ✅     | Même UID que la recherche |

**Exemple :**
```bash
curl "http://localhost:5000/stream?film=1&uid=123"
```

**Réponse :**
```json
{
  "title": "The Young Master",
  "index": 1,
  "streams": [],
  "downloads": [],
  "direct_download_url": "https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/download?subjectId=568239684535599800",
  "detail": {
    "title": "The Young Master",
    "description": "A talented martial arts student goes after his expelled brother...",
    "releaseDate": "1980-02-09",
    "duration": 6300,
    "genre": "Action,Adventure,Comedy",
    "country": "Hongkong, China",
    "imdbRating": "7.0",
    "cover_url": "https://..."
  }
}
```

## 🔄 Workflow complet

```bash
# Étape 1 : Rechercher
curl "http://localhost:5000/recherche?film=Jackie+Chan&uid=monTel"

# Étape 2 : Voir les détails du résultat #1
curl "http://localhost:5000/detail?film=1&uid=monTel"

# Étape 3 : Obtenir le lien de streaming/téléchargement
curl "http://localhost:5000/stream?film=1&uid=monTel"

# Pour le résultat #2
curl "http://localhost:5000/stream?film=2&uid=monTel"
```

## ⚙️ Fonctionnement technique

L'API utilise le mécanisme d'authentification suivant :
1. Génération d'un token client : `timestamp,MD5(timestamp_reversé)`
2. Requête GET à l'API MovieBox pour obtenir un cookie JWT
3. Utilisation du cookie pour les requêtes POST (recherche)

La recherche est mise en cache par `uid` pour éviter de refaire la recherche à chaque appel de `/stream` ou `/detail`.

## 📱 Utilisation sur téléphone

Pour utiliser l'API depuis votre téléphone :
1. Déployez l'API sur un serveur accessible publiquement
2. Utilisez un client HTTP (comme l'app "HTTP Request" sur Android)
3. Ou intégrez-la dans votre propre application mobile

```python
# Exemple d'intégration Python
import requests

API = "http://votre-serveur:5000"
UID = "monTel"

# Rechercher
r = requests.get(f"{API}/recherche", params={"film": "Jackie Chan", "uid": UID})
films = r.json()["results"]

# Afficher les titres
for f in films:
    print(f"{f['index']}. {f['title']} - {f['cover_url']}")

# Télécharger le premier
r = requests.get(f"{API}/stream", params={"film": 1, "uid": UID})
url = r.json()["direct_download_url"]
print(f"URL: {url}")
```

## 📂 Structure du projet

```
/Stream_movie/
  ├── server.py          # Code principal de l'API Flask
  ├── requirements.txt   # Dépendances Python
  ├── Dockerfile         # Image Docker pour Render.com
  ├── .dockerignore      # Fichiers exclus du build Docker
  ├── README.md          # Documentation
  └── cache/             # Cache des résultats de recherche
       └── search_results.json
```
