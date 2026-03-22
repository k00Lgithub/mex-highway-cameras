# Selangor Highway Cameras

Small Ruby app that shows the first 20 publicly available live highway camera
feeds it can fetch from the official Lembaga Lebuhraya Malaysia public CCTV
endpoints for Selangor-area highways.

## Local run

```bash
bundle install
bundle exec ruby server.rb
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
