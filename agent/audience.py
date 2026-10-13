"""Audience Pulse: what people are saying about recent and upcoming movies and shows.

Free sources only:
 - TMDB API (key: TMDB_KEY)     titles, studios / networks, popularity, user scores and reviews, posters
 - OMDb API (key: OMDB_KEY)     IMDb rating, Rotten Tomatoes %, Metascore, box office (1,000 free calls a day)
 - Reddit API (REDDIT_ID / REDDIT_SECRET, optional)   posts and comments in film & TV communities
 - Trade-press RSS feeds        Deadline, Variety, The Hollywood Reporter, IndieWire
Nothing is scraped from sites whose terms forbid it (Box Office Mojo, Rotten Tomatoes pages, Letterboxd).
"""
import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import news as newsmod
from .settings import read_csv, read_json
from .verify import flat, scrub

TMDB = "https://api.themoviedb.org/3"
POSTER = "https://image.tmdb.org/t/p/w342"
SUBS_MOVIE = "movies+boxoffice+marvelstudios+DC_Cinematic"
SUBS_TV = "television+marvelstudios+DC_Cinematic"

TITLE_SYSTEM = """You summarise ONLINE AUDIENCE OPINION about movies and TV shows from numbered text snippets
(user reviews, forum comments, trade-press headlines). Rules:
- Use ONLY the supplied text for each title. Do not use outside knowledge about the title.
- Every number you write must appear in that title's text. Ratings given in the header are facts you may use.
- Box-office verdict only if the text says so (e.g. 'hit', 'opened above/below expectations'); else "not stated".
- For upcoming titles there are no reviews: describe anticipation (praises = what people look forward to,
  complaints = concerns) and set box_office_verdict to "not stated".
- Short, neutral phrases. Return ONE JSON object."""

TITLE_SCHEMA = """{"titles": [{"key": "the key given", "audience_sentiment": "Positive|Mixed|Negative",
 "audience_score": integer from -100 (very negative) to 100 (very positive),
 "critics_vs_audience": "Critics higher|Audience higher|Aligned|Unclear", "gap_note": "short or null",
 "praises": ["up to 3 short phrases"], "complaints": ["up to 3 short phrases"],
 "buzz": "High|Medium|Low", "box_office_verdict": "hit|on track|under-performing|not stated",
 "summary": "one line"}]}"""


class TMDBClient:
    def __init__(self, key):
        self.key = (key or "").strip()
        self.s = requests.Session()
        if len(self.key) > 60:  # the long "Read Access Token" works too
            self.s.headers["Authorization"] = f"Bearer {self.key}"
        self.calls = 0

    def get(self, path, **params):
        if len(self.key) <= 60:
            params["api_key"] = self.key
        for attempt in range(3):
            r = self.s.get(f"{TMDB}{path}", params=params, timeout=25)
            self.calls += 1
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 401:
                raise RuntimeError("TMDB refused the key (check the TMDB_KEY secret)")
            if r.status_code == 404:
                return {}
            time.sleep(2)
        return {}


def _norm(x):
    return re.sub(r"\s+", " ", (x or "").strip().lower())


def load_studios():
    rows = []
    for r in read_csv("studios.csv"):
        if not r.get("studio"):
            continue
        rows.append({"studio": r["studio"].strip(), "parent": (r.get("parent") or "").strip(),
                     "group": (r.get("group") or "Rest of industry").strip(), "kind": (r.get("kind") or "").strip(),
                     "match": [_norm(m) for m in (r.get("match") or r["studio"]).split("|") if m.strip()],
                     "network_id": (r.get("tmdb_network_id") or "").strip()})
    return rows


def match_studio(names, studios):
    """First tracked-company studio found wins; otherwise the first rest-of-industry one; otherwise 'Other'."""
    norm = [_norm(n) for n in names if n]
    for group in ("Tracked companies", "Rest of industry"):
        for n in norm:
            for s in studios:
                if s["group"] == group and n in s["match"]:
                    return s
    if norm:
        return {"studio": names[0], "parent": names[0], "group": "Rest of industry", "kind": "other"}
    return None


def check_network_ids(tm, studios, log):
    """Make sure each TMDB network id in studios.csv really is that network (ids are checked, never trusted)."""
    ok = {}
    for s in studios:
        nid = s.get("network_id")
        if not nid or not nid.isdigit():
            continue
        d = tm.get(f"/network/{nid}")
        name = _norm(d.get("name"))
        if name and (name in s["match"] or any(m in name or name in m for m in s["match"] if len(m) > 2)):
            ok[nid] = s
        else:
            log.append(f"studios.csv: TMDB network id {nid} is '{d.get('name')}', not {s['studio']}; ignored")
    return ok


def company_ids(tm, studios, cache):
    """TMDB company ids for the tracked film studios (found by name once, then remembered)."""
    out = {}
    for s in studios:
        if s["group"] != "Tracked companies" or s["kind"] != "film":
            continue
        key = s["studio"]
        if key not in cache:
            res = tm.get("/search/company", query=s["studio"]).get("results") or []
            exact = [r["id"] for r in res if _norm(r.get("name")) in s["match"]]
            cache[key] = exact[:2]
        for cid in cache[key]:
            out[cid] = s
    return out


def discover(tm, studios, settings, log, cache):
    today = date.today()
    back = (today - timedelta(days=settings["PULSE_DAYS_BACK"])).isoformat()
    ahead = (today + timedelta(days=settings["PULSE_DAYS_AHEAD"])).isoformat()
    t = today.isoformat()
    found = {}

    def add(kind, results):
        for r in results or []:
            found.setdefault(f"{kind}-{r['id']}", (kind, r["id"], r.get("popularity") or 0))

    movie_base = dict(region="US", sort_by="popularity.desc", with_release_type="2|3|4", include_adult="false")
    for page in (1, 2, 3, 4):
        add("movie", tm.get("/discover/movie", **movie_base, page=page,
                            **{"release_date.gte": back, "release_date.lte": t}).get("results"))
    for page in (1, 2):
        add("movie", tm.get("/discover/movie", **movie_base, page=page,
                            **{"release_date.gte": t, "release_date.lte": ahead}).get("results"))
    cids = company_ids(tm, studios, cache.setdefault("company_ids", {}))
    if cids:
        ids = "|".join(str(c) for c in cids)
        add("movie", tm.get("/discover/movie", **movie_base, with_companies=ids,
                            **{"release_date.gte": back, "release_date.lte": ahead}).get("results"))
    tv_base = dict(sort_by="popularity.desc", include_adult="false")
    for page in (1, 2, 3):
        add("tv", tm.get("/discover/tv", **tv_base, page=page, with_original_language="en",
                         **{"air_date.gte": back, "air_date.lte": t}).get("results"))
    add("tv", tm.get("/discover/tv", **tv_base, with_original_language="en",
                     **{"first_air_date.gte": t, "first_air_date.lte": ahead}).get("results"))
    nets = check_network_ids(tm, studios, log)
    tracked_nets = [nid for nid, s in nets.items() if s["group"] == "Tracked companies"]
    for nid in tracked_nets:
        add("tv", tm.get("/discover/tv", **tv_base, with_networks=nid,
                         **{"air_date.gte": back, "air_date.lte": ahead}).get("results"))
    return found


def details(tm, kind, tid, studios):
    d = tm.get(f"/{kind}/{tid}", append_to_response="external_ids,reviews")
    if not d:
        return None
    if kind == "movie":
        names = [c.get("name") for c in d.get("production_companies") or []]
        rel = d.get("release_date") or ""
        title = d.get("title")
    else:
        names = [n.get("name") for n in d.get("networks") or []] + [c.get("name") for c in d.get("production_companies") or []]
        first = d.get("first_air_date") or ""
        last = d.get("last_air_date") or ""
        # a brand-new show is 'upcoming' until it premieres; a returning show is dated by its latest episode
        rel = first if (not first or first > date.today().isoformat()) else (last or first)
        title = d.get("name")
    st = match_studio(names, studios)
    if not st or not title:
        return None
    reviews = [{"author": (r.get("author") or "")[:40], "rating": (r.get("author_details") or {}).get("rating"),
                "text": newsmod.clean(r.get("content"))[:500], "url": r.get("url")}
               for r in ((d.get("reviews") or {}).get("results") or [])[:4]]
    return {
        "key": f"{kind}-{tid}", "kind": kind, "tmdb_id": tid, "title": title,
        "studio": st["studio"], "parent": st["parent"], "group": st["group"],
        "companies": [n for n in names if n][:5],
        "release_date": rel or None, "first_air_date": d.get("first_air_date") if kind == "tv" else None,
        "upcoming": bool(rel and rel > date.today().isoformat()) if kind == "movie" else bool(
            d.get("first_air_date") and d["first_air_date"] > date.today().isoformat()),
        "poster": f"{POSTER}{d['poster_path']}" if d.get("poster_path") else None,
        "overview": (d.get("overview") or "")[:300],
        "popularity": round(float(d.get("popularity") or 0), 1),
        "tmdb_vote": d.get("vote_average") or None, "tmdb_votes": d.get("vote_count") or 0,
        "imdb_id": (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id"),
        "tmdb_url": f"https://www.themoviedb.org/{kind}/{tid}",
        "tmdb_reviews": reviews,
    }


def omdb(key, imdb_id, cache):
    if not key or not imdb_id:
        return {}
    c = cache.get(imdb_id)
    if c and c.get("_at", "") >= (date.today() - timedelta(days=3)).isoformat():
        return c
    try:
        r = requests.get("https://www.omdbapi.com/", params={"apikey": key, "i": imdb_id}, timeout=20)
        d = r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        d = {}
    if d.get("Response") != "True":
        if "limit" in str(d.get("Error", "")).lower():
            raise RuntimeError("OMDb daily limit reached")
        return c or {}

    def num(x, cut=None):
        try:
            x = str(x).replace(",", "").replace("$", "").replace("%", "")
            if cut:
                x = x.split(cut)[0]
            return float(x)
        except Exception:  # noqa: BLE001
            return None
    ratings = {x.get("Source"): x.get("Value") for x in d.get("Ratings") or []}
    out = {"imdb_rating": num(d.get("imdbRating")), "imdb_votes": num(d.get("imdbVotes")),
           "rt": num(ratings.get("Rotten Tomatoes")), "metascore": num(d.get("Metascore")),
           "box_office_usd": num(d.get("BoxOffice")), "_at": date.today().isoformat()}
    cache[imdb_id] = out
    return out


class Reddit:
    def __init__(self, cid, secret):
        self.token = None
        self.ua = "client-intel-dashboard/1.0 (audience pulse; free script app)"
        if not (cid and secret):
            return
        try:
            r = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                              data={"grant_type": "client_credentials"}, headers={"User-Agent": self.ua}, timeout=20)
            self.token = r.json().get("access_token") if r.status_code == 200 else None
            if not self.token:
                print(f"   (Reddit login failed: HTTP {r.status_code}; skipping Reddit)")
        except Exception as e:  # noqa: BLE001
            print(f"   (Reddit unavailable: {type(e).__name__}; skipping Reddit)")

    def ok(self):
        return bool(self.token)

    def _get(self, path, **params):
        r = requests.get(f"https://oauth.reddit.com{path}", params=params, timeout=20,
                         headers={"Authorization": f"bearer {self.token}", "User-Agent": self.ua})
        time.sleep(1.1)  # Reddit's free limit is about 100 requests a minute
        return r.json() if r.status_code == 200 else {}

    def talk(self, title, kind):
        subs = SUBS_MOVIE if kind == "movie" else SUBS_TV
        res = self._get(f"/r/{subs}/search", q=f'"{title}"', restrict_sr=1, sort="relevance", t="month", limit=6)
        posts = [c["data"] for c in (res.get("data") or {}).get("children", [])]
        posts = [p for p in posts if _norm(title) in _norm(p.get("title"))][:3]
        out = []
        for p in posts:
            out.append({"kind": "post", "sub": p.get("subreddit"), "text": newsmod.clean(p.get("title"))[:200],
                        "score": p.get("score"), "url": "https://www.reddit.com" + p.get("permalink", "")})
        if posts:
            com = self._get(f"/comments/{posts[0]['id']}", limit=8, depth=1, sort="top")
            if isinstance(com, list) and len(com) > 1:
                for c in (com[1].get("data") or {}).get("children", [])[:6]:
                    body = newsmod.clean((c.get("data") or {}).get("body"))
                    if body and len(body) > 30:
                        out.append({"kind": "comment", "sub": posts[0].get("subreddit"), "text": body[:260],
                                    "score": (c.get("data") or {}).get("score"), "url": out[0]["url"]})
        return out


def trade_items(days=30):
    """Movies & TV trade press: their own feeds, or a Google News search of the site if a feed fails."""
    items, status = [], []
    for f in read_csv("feeds.csv"):
        if (f.get("area") or "").strip() != "Movies & TV":
            continue
        got, err = ([], "no feed")
        if (f.get("url") or "").strip():
            got, err = newsmod.fetch_feed(f["url"].strip(), f["name"])
            for g in got:
                g["source"] = f["name"]
        if not got and f.get("site"):
            got = newsmod.google_news(f"site:{f['site'].strip()} (box office OR review OR ratings)", days)
            status.append({"area": "Movies & TV", "name": f["name"], "ok": bool(got),
                           "via": "Google News (site search)", "error": err})
        else:
            status.append({"area": "Movies & TV", "name": f["name"], "ok": bool(got), "via": "RSS feed", "error": err})
        items += got
    return newsmod.dedupe(newsmod.recent(items, days)), status


def title_text(t, trade):
    """All the text about one title, trimmed to fit the free AI limit (about 2,600 characters)."""
    parts = []
    rat = [f"TMDB user score {t['tmdb_vote']}/10 ({t['tmdb_votes']} votes)" if t.get("tmdb_vote") else None,
           f"IMDb {t['imdb_rating']}/10" if t.get("imdb_rating") else None,
           f"Rotten Tomatoes {t['rt']:.0f}%" if t.get("rt") is not None else None,
           f"Metascore {t['metascore']:.0f}/100" if t.get("metascore") is not None else None,
           f"US box office ${t['box_office_usd']:,.0f}" if t.get("box_office_usd") else None]
    parts.append("Ratings: " + ("; ".join(r for r in rat if r) or "none yet"))
    for r in t.get("tmdb_reviews") or []:
        rating = f" ({r['rating']}/10)" if r.get("rating") else ""
        parts.append(f"TMDB review{rating}: {r['text'][:380]}")
    for x in t.get("reddit") or []:
        parts.append(f"Reddit r/{x.get('sub')} {x['kind']}: {x['text']}")
    for x in trade[:4]:
        parts.append(f"{x.get('source')} headline: {x['title']}" + (f" — {x['snippet'][:160]}" if x.get("snippet") else ""))
    text = "\n".join(parts)
    return text[:2600]


def trade_for(title, trade):
    nt = _norm(title)
    if len(nt) < 4:
        return []
    pat = re.compile(rf"(?<![a-z0-9]){re.escape(nt)}(?![a-z0-9])")
    return [x for x in trade if pat.search(_norm(x["title"]))][:5]


def analyse_batch(llm, batch):
    blocks = []
    for t in batch:
        head = (f"KEY {t['key']} | {t['title']} ({'movie' if t['kind'] == 'movie' else 'TV show'}, "
                f"{t['studio']}, {'releases' if t['upcoming'] else 'released'} {t.get('release_date') or 'date unknown'})")
        blocks.append(head + "\n" + t["_text"])
    user = ("Titles:\n\n" + "\n\n".join(blocks) + f"\n\nReturn JSON exactly in this shape (one entry per KEY):\n{TITLE_SCHEMA}")
    out = llm.chat_json(TITLE_SYSTEM, user, max_tokens=2200)
    res = {}
    by_key = {t["key"]: t for t in batch}
    for x in out.get("titles") or []:
        k = x.get("key")
        if k not in by_key:
            continue
        dropped = []
        scrub(x, flat(by_key[k]["_text"] + " " + by_key[k]["title"]), dropped)
        try:
            x["audience_score"] = max(-100, min(100, int(x.get("audience_score"))))
        except (TypeError, ValueError):
            x["audience_score"] = None
        for f, allowed in (("audience_sentiment", ("Positive", "Mixed", "Negative")),
                           ("buzz", ("High", "Medium", "Low")),
                           ("box_office_verdict", ("hit", "on track", "under-performing", "not stated")),
                           ("critics_vs_audience", ("Critics higher", "Audience higher", "Aligned", "Unclear"))):
            v = str(x.get(f) or "")
            x[f] = next((a for a in allowed if a.lower() == v.lower()), None)
        x["praises"] = [p for p in (x.get("praises") or []) if isinstance(p, str)][:3]
        x["complaints"] = [p for p in (x.get("complaints") or []) if isinstance(p, str)][:3]
        x["unverified_dropped"] = dropped
        x["analysed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        res[k] = x
    return res


def run(settings, llm, log, force=False, skip_ai=False):
    """Returns (titles, feed_status). Reuses yesterday's AI notes when nothing new has been said about a title."""
    if not settings.get("TMDB_KEY"):
        print("   Skipped: no TMDB_KEY secret yet (see the guide, step 4).")
        log["errors"].append("audience pulse: TMDB_KEY missing")
        return None, []
    tm = TMDBClient(settings["TMDB_KEY"])
    studios = load_studios()
    cache = read_json("pulse_cache.json", {})
    old = {t["key"]: t for t in read_json("pulse_titles.json", {}).get("titles", [])}
    errs = []
    found = discover(tm, studios, settings, errs, cache)
    print(f"   TMDB: {len(found)} candidate titles")
    cands = []
    for key, (kind, tid, pop) in sorted(found.items(), key=lambda kv: -kv[1][2])[:140]:
        try:
            d = details(tm, kind, tid, studios)
        except RuntimeError as e:
            log["errors"].append(f"audience pulse: {e}")
            return None, []
        if d:
            cands.append(d)
    pick = []
    for group in ("Tracked companies", "Rest of industry"):
        g = [c for c in cands if c["group"] == group]
        g.sort(key=lambda c: -(c["popularity"] or 0))
        pick += [c for c in g if not c["upcoming"]][: settings["PULSE_TITLES_PER_GROUP"]]
        pick += [c for c in g if c["upcoming"]][: settings["PULSE_UPCOMING_PER_GROUP"]]
    print(f"   Tracking {len(pick)} titles ({sum(not p['upcoming'] for p in pick)} out now, "
          f"{sum(p['upcoming'] for p in pick)} upcoming)")
    trade, status = trade_items()
    reddit = Reddit(settings.get("REDDIT_ID"), settings.get("REDDIT_SECRET"))
    if not reddit.ok():
        print("   Reddit not set up (optional) - skipping it.")
    omdb_cache = cache.setdefault("omdb", {})
    omdb_ok = bool(settings.get("OMDB_KEY"))
    for t in pick:
        if omdb_ok and not t["upcoming"]:
            try:
                t.update({k: v for k, v in omdb(settings["OMDB_KEY"], t.get("imdb_id"), omdb_cache).items() if not k.startswith("_")})
            except RuntimeError as e:
                omdb_ok = False
                errs.append(f"OMDb: {e}")
        if reddit.ok():
            try:
                t["reddit"] = reddit.talk(t["title"], t["kind"])
            except Exception as e:  # noqa: BLE001
                t["reddit"] = []
                errs.append(f"Reddit {t['title']}: {type(e).__name__}")
        t["trade"] = [{"title": x["title"], "link": x["link"], "source": x.get("source"),
                       "published": (x.get("published") or "")[:10], "snippet": x.get("snippet", "")}
                      for x in trade_for(t["title"], trade)]
        t["_text"] = title_text(t, t["trade"])
        t["input_hash"] = hashlib.sha1(t["_text"].encode()).hexdigest()[:12]
    if not settings.get("OMDB_KEY"):
        errs.append("OMDb: OMDB_KEY missing (IMDb/RT/Metascore not shown)")
    # AI only where something new has been said, and only with enough text to read
    todo = []
    for t in pick:
        prev = old.get(t["key"], {})
        fresh = (prev.get("ai") or {}).get("analysed_at", "") >= (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        enough = len(t["_text"]) > 120 or t["upcoming"]
        if prev.get("ai") and not force and (prev.get("input_hash") == t["input_hash"] or fresh):
            t["ai"] = prev["ai"]
        elif enough:
            todo.append(t)
    if not skip_ai and llm.available() and todo:
        print(f"   AI reading {len(todo)} titles (others unchanged since last time)...")
        for i in range(0, len(todo), 3):
            batch = todo[i:i + 3]
            try:
                res = analyse_batch(llm, batch)
                for t in batch:
                    if t["key"] in res:
                        t["ai"] = res[t["key"]]
                    elif old.get(t["key"], {}).get("ai"):
                        t["ai"] = old[t["key"]]["ai"]
            except Exception as e:  # noqa: BLE001
                errs.append(f"pulse AI: {e}")
                print(f"      AI problem: {e}")
                if "allowance" in str(e) or "refused" in str(e):
                    break
    for t in pick:
        t.pop("_text", None)
        if "ai" not in t and old.get(t["key"], {}).get("ai"):
            t["ai"] = old[t["key"]]["ai"]
    from .settings import write_json
    write_json("pulse_cache.json", cache)
    log["errors"] += errs
    return pick, status
