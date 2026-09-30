# Project guidance

- Run Python tests with `./venv/bin/python -m unittest discover -s tests -v`.
- Verify syntax with `./venv/bin/python -m compileall -q analysis storage analysis_cli.py`.
- The current Gradio/Hugging Face interface must remain functional while the analysis backend evolves.
- A later phase will replace the Hugging Face application with a Vercel-hosted Next.js application; keep analysis and provider logic independent from Gradio to support that migration.
- API credentials must come from environment variables and must never be committed.
