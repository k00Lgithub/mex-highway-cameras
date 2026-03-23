# MEX Highway Cameras

Small Python app that shows all publicly available live highway camera feeds it
can fetch for the MEX Highway from the official Lembaga Lebuhraya Malaysia
public CCTV endpoints.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:4567/`.

## Heroku deploy

```bash
heroku login
heroku create your-app-name
git init
git add .
git commit -m "Initial deploy"
git push heroku main
heroku open
```

If your local Git branch is `master`, use:

```bash
git push heroku master:main
```

## Render deploy

1. Push this repo to GitHub.
2. In Render, create a new `Web Service` from that GitHub repo.
3. Render can use the included [render.yaml](/Users/jerry/Documents/dev_stuff/codex/hello_world/render.yaml), or you can enter these settings manually:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

4. Deploy the service.

After deploy, open the Render URL and the app should load on `/`.
