# Data sources

tg_sales works offline. The only features that use the internet are game
discovery and, when you click a link, opening a web page in your browser.
This page lists every external source, what it provides, its limits, and how
tg_sales uses it.

## Steam store (game discovery)

**Used for:** finding games with upcoming or recent releases and reading
their public store details.

| Endpoint | What it provides | Used how |
|----------|------------------|----------|
| `store.steampowered.com/search/results/?json=1` | Pages of games that are "coming soon" or newest releases; each result has only a name and an image URL (the app id is read from the image URL) | Candidate list when you choose **Find games** |
| `store.steampowered.com/api/featuredcategories` | Short "Coming soon" and "New releases" lists | Extra candidates |
| `store.steampowered.com/api/appdetails?appids=…` | Type (game, DLC, demo), developers, publishers, release date or "Coming soon", genres, categories, platforms, languages, official website, and a support email or URL the developer chose to publish | Details of each game |

**Permissions and conduct.** These are public storefront endpoints, not the
documented Steam Web API. The store's `robots.txt` does not disallow `/api/`
or `/search/`. tg_sales:

- only contacts Steam when you start a search or add links;
- sends at most one request every 1.5 seconds, identifies itself in its
  User-Agent, and backs off (honoring `Retry-After`) when asked to slow down;
- stops asking Steam for the rest of a run after HTTP 429 (too many requests)
  or 401/403 (access refused), and never tries to work around captchas,
  logins, paywalls or other access controls;
- caches game details for 24 hours in the local `cache\discovery\steam`
  folder and uses the cached copy, clearly marked as not current, when Steam
  cannot be reached.

**Limits.**

- Steam does not publish a complete catalog of future releases or a contact
  directory. Search returns a selection (currently popular "coming soon" and
  newest games); a game you know about may not appear. Use **Add Steam
  links…** to add specific games by link or app id.
- Release dates may be exact, a month, a quarter, a year, or not announced
  ("Coming soon", "To be announced"); tg_sales keeps the precision and
  Steam's original wording.
- Region-specific data is not available: results reflect the US English
  store. There is no reliable region or company-size information, so
  tg_sales does not filter or score by them.
- Valve can change or restrict these endpoints at any time; discovery then
  reports the error and keeps your saved results.

**Attribution.** Discovery results are labeled "Game data from the public
Steam store", and each result links to its Steam store page.

## Studio websites (optional contact check)

**Used for:** looking for a business email address on a studio's official
website, only when you click **Check studio website…** for one game.

tg_sales reads the site's `robots.txt` and respects it, then reads the home
page and at most two pages on the same site whose links mention contact,
press, business, legal or about information. It returns only addresses that
actually appear on those pages, each with the page it came from. Nothing is
saved until you choose an address, and it is stored as "needs verification".

## Contact provenance

tg_sales never invents or guesses contact details, and never collects private
details from personal profiles. Every discovered contact records where it
came from:

| Status | Meaning |
|--------|---------|
| Not found | No address is published on a public page that tg_sales checked |
| Needs verification | An address published on a named public page (the Steam store support contact or a studio web page); check that it is appropriate for business outreach before using it |
| Verified source | You confirmed the address and its source yourself |

When a discovered contact is saved to Prospects, the contact's
*Where this came from* and *Source page* fields keep this provenance. The
Steam support address is chosen by the developer for player support; for
very small studios it may belong to an individual. Use it only for relevant,
professional outreach, identify yourself, and honor opt-out requests.

## Lead scoring

Scores are sums of simple, visible rules (shown with every score):

| Rule | Points |
|------|--------|
| Releases within the upcoming window | +30 |
| Released within the recent window | +20 |
| Release date not announced | +5 |
| Self-published (developer is also the publisher) | +15 |
| Official website listed | +10 |
| Public business contact found | +15 |
| Each target genre (at most two) | +10 |
| Downloadable content of another game | −20 |

The total is capped between 0 and 100. *Confidence* describes how complete
the underlying data is (announced date, developer, genres, freshly
retrieved), not a prediction of success.

## Other stores

Google Play and the Apple App Store are not supported yet. They are
registered as disabled sources and will only be enabled once an adapter based
on a permitted data source exists.
