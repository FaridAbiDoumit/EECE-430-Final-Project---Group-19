Groq setup for local AI analytics:

- The Groq API key is stored as a user environment variable named `GROQ_API_KEY`.
- The default model is stored as a user environment variable named `GROQ_MODEL`.
- The app reads these values at runtime from the server environment and does not store secrets in the repo.
- If the key is missing, the AI analytics hub falls back to deterministic local summaries.

Recommended local check in PowerShell:

```powershell
[bool][Environment]::GetEnvironmentVariable('GROQ_API_KEY', 'User')
[Environment]::GetEnvironmentVariable('GROQ_MODEL', 'User')
```
