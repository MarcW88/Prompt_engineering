# Project guidance

- Run Python tests with `./venv/bin/python -m unittest discover -s tests -v`.
- Verify syntax with `./venv/bin/python -m compileall -q analysis storage analysis_cli.py`.
- The production interface is the root Next.js application deployed on Vercel.
- Keep Python collection and analysis modules independent from the Next.js interface.
- Version production schema changes in `supabase/migrations/`.
- API credentials must come from environment variables and must never be committed.
