> **⚠️ Archived — superseded by [bounty-watch](https://github.com/abdulsalam-create/bounty-watch).**
> bounty-watch keeps the program ranking (now an additive, freshness-weighted [hunt score](https://abdulsalam-create.github.io/bounty-watch/)) and adds YesWeHack, daily monitoring, scope/deploy/new-feature change alerts by email, and a live dashboard.

# Bounty Scout

A CLI tool that picks bug bounty programs worth hunting on. It pulls public
program data from HackerOne, Bugcrowd and Intigriti, scores every open program
by expected value and dupe risk, and prints a ranked list with a "why" for
each entry. No login, no API keys, all data is cached locally.

Program choice is what drives dupe rates. Picking a small program with fast
triage and a decent payout beats grinding a big one with 300 other hunters on
it. This tool applies that logic to the full program directories of the three
biggest platforms and saves you the manual checking.

## Features

- Ranks programs across HackerOne, Bugcrowd and Intigriti by expected value
  and dupe risk
- Shows why each program scored the way it did (triage speed, payout, activity,
  competition, wildcard scope)
- Filters the ranking by bug class (idor, auth, business_logic,
  response_manipulation) using scope keywords
- Pulls scopes and rewards for the top candidates so the ranking is based on
  real data, not just directory listings
- Exports the ranked list to CSV
- Same features available in a browser at http://127.0.0.1:5000
- Caches everything on disk. Running the tool again is instant and sends zero
  requests to the platforms

## Project structure

```
bounty-scout/
├── main.py        # CLI menu and prompts
├── app.py         # web interface (Flask), same logic as the CLI
├── templates/     # the web page
├── tools.py       # thin handlers used by the CLI and the web app
├── fetch.py       # requests, caching, one fetcher per platform endpoint
├── rules.py       # normalizing, scoring, ranking, bug class filter
├── requirements.txt
└── cache/         # created on first run, holds downloaded data
```

## Setup

```
git clone https://github.com/abdulsalam-create/bounty-scout.git
cd bounty-scout
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

No API keys, no accounts, nothing to configure. The first run downloads the
full program directories, which takes about 2.5 minutes for HackerOne alone.
Everything after that is cached (HackerOne data for a week, the rest daily).

## Usage

```
============================================================
  Bounty Scout - bug bounty program picker
============================================================
  Data from HackerOne, Bugcrowd and Intigriti public endpoints.
  Cached locally, no API keys needed.

  1. Rank programs (dupe risk + expected value)
  2. Filter by bug class (idor / auth / business_logic / response_manipulation)
  3. Refresh platform data
  4. Show one program in detail
  5. Export ranked list to CSV
  Pick a mode (1/2/3/4/5):
```

Pick a mode and answer the prompts. Pressing enter picks the defaults
(all platforms, top 10).

### Example: rank

```
  Platforms (hackerone, bugcrowd, intigriti, all = enter):
  Top N (default 10):
  Minimum average payout $ (default 0):

 1. 146.8  Agoda Public                             hackerone    $1604  5       payout 1604 -> factor 1.68
 2.  81.1  Vercel Sandbox                           hackerone        ?  2       payout unknown, neutral 0.7
 3.  57.2  Wolt                                     hackerone      $50  3       payout 50 -> factor 0.50
 4.  38.4  Blend Labs                               hackerone     $750  13      payout 750 -> factor 1.00
 5.  37.4  Banco Plata                              hackerone     $300  16      payout 300 -> factor 0.64
 6.  37.2  WisdomTree, Inc.                         hackerone    $1250  54      payout 1250 -> factor 1.40
 7.  36.8  TRON DAO                                 hackerone     $350  13      payout 350 -> factor 0.68
 8.  36.1  NVIDIA Public Bug Bounty                 intigriti    $7575  ~60      payout 7575 -> factor 2.00
 9.  34.9  ALSCO                                    hackerone     $205  7       payout 205 -> factor 0.56
10.  34.8  Temu                                     hackerone    $1015  33      payout 1015 -> factor 1.21

  10 programs, 0 details fetched fresh
```

The participants column is the hunter count (lower is better). A `~` means the
count is an estimate, since Bugcrowd and Intigriti do not publish it directly.
The last column is the first line of the breakdown; mode 4 prints the whole
thing.

### Example: filter by bug class

```
  Bug class (idor, auth, business_logic, response_manipulation): idor
  Platforms (hackerone, bugcrowd, intigriti, all = enter):
  Top N (default 10): 5

 1.  57.2  Wolt                                     hackerone      $50  3       scope matches 'idor' keywords
 2.  37.4  Banco Plata                              hackerone     $300  16      scope matches 'idor' keywords
 3.  37.2  WisdomTree, Inc.                         hackerone    $1250  54      scope matches 'idor' keywords
 4.  36.1  NVIDIA Public Bug Bounty                 intigriti    $7575  ~60      scope matches 'idor' keywords
 5.  30.7  Starbucks Japan                          hackerone     $515  19      scope matches 'idor' keywords
```

Programs whose scope was never fetched show `scope unknown, kept` so you can
decide for yourself. Only the top candidates per platform get their scopes
fetched, to keep the request count low.

### Example: refresh

```
  Platforms (hackerone, bugcrowd, intigriti, all = enter): bugcrowd,intigriti
  bugcrowd: engagements 265, crowdstream_items 80, cache_hit False
  intigriti: programs 182, cache_hit False
```

Refreshing HackerOne takes about 2.5 minutes (64 pages of teams).

### Example: one program in detail

```
  Platform (hackerone, bugcrowd, intigriti): hackerone
  Handle (program slug): agoda-public

  Agoda Public (hackerone/agoda-public)
  score 146.8 | avg payout $1604.0 | participants 5
  why:
    - payout 1604 -> factor 1.68
    - first response 0h < 24h -> 1.5
    - bounty time 0d -> 1.5
    - response efficiency 91% -> 1.3
    - no wildcard scope -> 1.0
    - participants 5 < 150, low dupe risk
  scope (1):
    - https://www.agoda.com/book/
```

### Example: export

```
  Platforms (hackerone, bugcrowd, intigriti, all = enter):
  Top N (default 20):
  wrote 20 rows to top_programs.csv
```

## Web interface

The same tool is available in a browser. Start it with:

```
python app.py
```

Then open http://127.0.0.1:5000. The page has the same five modes: rank,
filter by bug class, one program in detail, refresh data, and a CSV download.
Everything runs on your machine; nothing is sent anywhere except the platform
requests themselves.

## How the score works

```
score = payout x response x health x wildcard x 100 / sqrt(participants)
```

Four factors, each capped so nothing dominates:

- **payout** - average bounty in dollars, scaled from 0.5x to 2.0x
- **response** - how fast the program answers reports (HackerOne SLA data,
  Intigriti activity timing, Bugcrowd is approximated)
- **health** - is the program alive: recent accepted submissions, response
  efficiency, quiet programs get penalized
- **wildcard** - wildcard scopes like `*.example.com` score 1.2x
- **participants** - competition. The score is divided by the square root of
  the hunter count, so 5 hunters is roughly 4x better than 80

Every factor that had to be guessed (missing data, proxy numbers) shows up in
the breakdown as `approx:` or a `~` prefix on the participants column.

## Known limitations

- Bugcrowd does not publish triage speed, so response quality for Bugcrowd
  programs is a neutral guess
- Bugcrowd and Intigriti hunter counts are estimates (crowdstream researchers,
  contributors and submission counts)
- Scopes are only fetched for the top candidates per platform, not for all
  thousands of programs
- The bug class filter matches scope keywords, which is a heuristic, not a
  guarantee. Always read the scope before hunting
- The tool talks to the platforms as an unauthenticated guest, so it sees
  public programs only. Private invitations are not visible

## License

MIT
