# EECE 430 Final Project

Fresh Django codebase for Sprint 1 implementation.

## Sprint 1 focus
- Training session creation
- Next session view
- RSVP flow
- Coach RSVP overview

## Setup
```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Docker
Prerequisite: Docker Desktop must be installed and running.

Build the image:
```powershell
docker build -t eece430-volley-app .
```

Run the container:
```powershell
docker run -p 8000:8000 -d eece430-volley-app
```

Open the site at `http://localhost:8000/`.

Notes:
- The image already contains the current repository `db.sqlite3`, and the container runs migrations automatically on startup.
- If you remove the container and run a new one, the database resets to the image copy. That is usually fine for a demo.
- AI analytics stays optional. In PowerShell, set `GROQ_API_KEY` before `docker run` if you want it enabled.

```powershell
$env:GROQ_API_KEY="your-key"
docker run -p 8000:8000 -d eece430-volley-app
```

Useful demo commands:
```powershell
docker ps
docker logs <container_id>
docker stop <container_id>
docker rm <container_id>
```

## Concurrent demo mode (multi-user)
- Django's `runserver` handles requests with threading enabled by default.
- This project also enables SQLite WAL mode and a lock timeout to make concurrent user actions more reliable during demos.

Run the server for local multi-user testing:
```powershell
python manage.py runserver 0.0.0.0:8000 --noreload
```

Tips for messaging demos:
- Sign in with different users in separate browser profiles/incognito windows.
- Use `http://127.0.0.1:8000/` for all sessions.

