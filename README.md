# VLRAG
## [App Link](https://vlrag-688k.onrender.com/)


## Environment variables
The backend expects the following environment variables:
- `OPENAI_API_KEY` – OpenAI API key used for LLM calls.
- `SUPABASE_URL` – Supabase project URL (e.g. `https://<project>.supabase.co`).
- `SUPABASE_ANON_KEY` – Supabase anon key used by the backend.
- `SUPABASE_SERVICE_ROLE_KEY` – (Optional) Supabase service role key for privileged operations.
- `ENV` – Environment marker (`local`, `dev`, `prod`), defaults to `local`.

For local development:
1. Copy `.env.example` to `.env`.
2. Fill in the appropriate values.
3. `python -m venv .venv` and activate it.
4. `pip install -r requirements.txt`.
5. Run the app with `uvicorn` (see deployment instructions).

On Render:
- Configure the same environment variables in the Render dashboard under **Environment → Environment Variables** for the backend service.
