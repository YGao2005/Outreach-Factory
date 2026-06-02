# Twitter/X cookie auth for /research-prospect

To scrape a prospect's actual tweets (past the bio), x.com requires an authenticated session. The `/research-prospect` skill reads a cookie file from this directory by default. The path is overridable in `~/.outreach-factory/config.yml` under `scraper_auth.twitter_cookies_path`.

## Setup (one-time, ~2 minutes)

1. **Log into x.com in Chrome** (regular browser, not incognito).

2. **Open DevTools** → `Application` tab → expand `Cookies` in the left sidebar → click `https://x.com`.

3. **Find these two cookies** and copy their `Value` field:
   - `auth_token` — long alphanumeric string
   - `ct0` — long alphanumeric string

4. **Create** `x.com-cookies.json` in this directory (or wherever `scraper_auth.twitter_cookies_path` points) with this content (replace the `...` with the values from step 3):

```json
[
  {
    "name": "auth_token",
    "value": "...",
    "domain": ".x.com",
    "path": "/",
    "secure": true,
    "httpOnly": true,
    "sameSite": "None"
  },
  {
    "name": "ct0",
    "value": "...",
    "domain": ".x.com",
    "path": "/",
    "secure": true,
    "sameSite": "Lax"
  }
]
```

5. **Verify** by running the skill on someone active on Twitter:
   ```
   /research-prospect "First Last" CompanyName
   ```
   Look for `Tweet {YYYY-MM-DD}: "..."` lines in the Phase 5 output. If you only see bio info, cookies didn't take.

## When cookies expire

Twitter session cookies typically last ~30 days. The skill detects expiry by looking for the logged-out marker (`Don't miss what's happening`) in the fetched page and prints:

```
⚠  Twitter cookies appear expired — refresh: see auth/README.md
```

When you see that warning, repeat steps 1-4 above to refresh.

## Security notes

- These cookies are **access tokens** for your X account. Anyone with them can read your DMs and post as you.
- This `auth/` directory has a local `.gitignore` that excludes `*.json`. **Never commit the JSON file.**
- If you suspect the cookies leaked (e.g., committed to a public repo by accident), **immediately log out everywhere** on x.com: Settings → Security → Sessions → log out all devices. This invalidates the tokens.
- Consider using a **throwaway X account** for this if you're privacy-paranoid. The skill works fine with any authenticated session.

## Why we don't use the official X API

- v2 API costs $100+/month for basic read access
- For low-volume prospect lookups, scraping a logged-in session is more cost-effective and gives richer data (replies, media, full posts)
- This is read-only personal use — within X's terms for non-commercial usage at low volume
