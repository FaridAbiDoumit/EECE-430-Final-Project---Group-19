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

