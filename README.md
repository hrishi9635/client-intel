# Industry Intelligence Dashboard (client-intel)

A free, automatic dashboard that follows 15 organisations in media & entertainment, gaming & lottery,
publishing & information, and education **as industry players**, focused on what matters to technology and
IT-services vendors. Cost: $0.

**Free sources:** SEC EDGAR (official US results, exact XBRL numbers), company releases, Yahoo Finance (yfinance),
Google News & Bing News RSS, trade-press RSS feeds, TMDB, OMDb, Reddit (optional), Groq's free AI tier,
GitHub Actions, Streamlit Community Cloud.

## Folder map
| File | What it is |
|---|---|
| `app.py` | The website (10 pages). |
| `companies.csv` | The 15 organisations, tickers, SEC numbers, search words. Edit in a text editor, not Excel. |
| `settings.txt` | AI model, limits, time windows. No secrets here. |
| `run_agent.py` + `agent/` | The agent. |
| `data/` | Everything the agent saves; the website reads it. You may edit `overrides.csv`, `studios.csv`, `feeds.csv`. |
| `.github/workflows/agent.yml` | The timetable that runs the agent on GitHub. |

## Secrets (GitHub → Settings → Secrets and variables → Actions)
`LLM_API_KEY` (Groq), `SEC_CONTACT` (your e-mail), `TMDB_KEY`, `OMDB_KEY`, optional `REDDIT_ID` + `REDDIT_SECRET`.

## Run by hand
GitHub → Actions → Run the agent → Run workflow (choose a part; "force = yes" re-analyses everything).

## Fixing a number
Add a line to `data/overrides.csv` (values in millions). It beats every other source on the next run.

Not investment advice. AI summaries can be wrong: check important facts against the linked sources.
