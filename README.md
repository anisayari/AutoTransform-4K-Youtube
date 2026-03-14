# AutoTransform-4K-Youtube

Petit studio Flask pour retravailler les miniatures de tes vidéos YouTube sans quitter ton navigateur.

L'app fait quatre choses :

- récupère la liste de tes vidéos via l'API officielle YouTube,
- télécharge la miniature existante avec l'API officielle, avec `pytube` en secours,
- envoie l'image à un modèle Gemini image configurable,
- réapplique la miniature générée sur la vidéo via `thumbnails.set`.

Le point important : tu choisis les vidéos à traiter. L'app ne transforme pas tout le catalogue d'un coup.

## Ce que le projet utilise

- `Flask` pour le backend et l'interface
- `google-api-python-client` pour YouTube Data API v3
- `google-auth-oauthlib` pour le login Google / YouTube
- `google-genai` pour la génération image
- `pytube` en fallback non officiel
- `Pillow` pour préparer un fichier propre pour YouTube

## Ce que l'interface permet déjà

- connexion OAuth Google
- chargement des vidéos de ta chaîne
- sélection multiple des vidéos à traiter
- transformation d'une seule vidéo ou d'une sélection
- conservation d'un master généré dans `instance/media/generated/`
- création automatique d'une version `1280x720` légère pour l'upload YouTube

## Prérequis

- Python 3.11+ recommandé
- un projet Google Cloud
- `YouTube Data API v3` activée
- un client OAuth Google de type Web application
- une clé Gemini

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Dans Google Cloud Console :

1. active `YouTube Data API v3`
2. crée un client OAuth `Web application`
3. ajoute `http://localhost:5001/auth/google/callback` dans les redirect URIs autorisées

## Lancer le projet

```bash
./start.sh
```

Au premier lancement, l'app ouvre un écran `Setup` si la config n'est pas prête.
Tu peux alors :

- coller ta clé Gemini depuis l'interface,
- uploader ton `client_secret.json` depuis l'interface,
- lancer ensuite la connexion YouTube.

Le script choisit aussi automatiquement un port libre si `5001` est déjà occupé.

Si tu préfères tout faire à la main, l'ancien flux marche aussi :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Dans ce cas, les variables minimales sont :

```env
FLASK_SECRET_KEY=une-cle-secrete
GEMINI_API_KEY=ta-cle-gemini
```

## Flux réel

1. clique sur `Connecter YouTube`
2. autorise l'accès à ta chaîne
3. charge tes vidéos
4. coche uniquement celles que tu veux retravailler
5. ajuste le prompt si besoin
6. lance la transformation
7. l'app réuploade la miniature sur la vidéo sélectionnée

## Variables utiles

- `GOOGLE_CLIENT_SECRETS_FILE` : chemin vers le fichier OAuth
- `GOOGLE_REDIRECT_URI` : callback OAuth
- `YOUTUBE_TOKEN_FILE` : fichier local qui stocke le token utilisateur
- `YOUTUBE_MAX_VIDEOS` : nombre max de vidéos à afficher
- `GEMINI_IMAGE_MODEL` : modèle image à utiliser
- `GEMINI_IMAGE_ASPECT_RATIO` : laisser `16:9`
- `GEMINI_IMAGE_SIZE` : `4K` si le modèle choisi le supporte
- `DEFAULT_TRANSFORM_PROMPT` : prompt chargé par défaut dans l'UI

## Structure rapide

```text
thumbnail_studio/
  services/
    auth.py
    gemini.py
    image_tools.py
    youtube.py
  static/
  templates/
tests/
run.py
```

## Tests

```bash
source .venv/bin/activate
pytest -q
```

La suite couvre pour l'instant :

- le rendu de l'app Flask
- la redirection automatique vers l'écran de setup
- la sauvegarde de la clé Gemini
- l'upload du `client_secret.json`
- le contrôle d'auth sur les endpoints API
- le batch de transformation sur une sélection de vidéos
- la préparation d'un thumbnail compatible YouTube

## Limites à connaître

- `pytube` n'est pas stable dans le temps. Ici il sert juste de roue de secours.
- YouTube demande un compte éligible aux miniatures personnalisées.
- Le rendu "4K" est conservé localement, mais l'upload final est volontairement redimensionné pour coller au format attendu par YouTube.
- Si ton compte n'a pas accès au modèle Gemini configuré, change `GEMINI_IMAGE_MODEL` dans `.env`.

## Sources utiles

- [YouTube Data API: thumbnails.set](https://developers.google.com/youtube/v3/docs/thumbnails/set)
- [Gemini API image generation](https://ai.google.dev/gemini-api/docs/image-generation)
