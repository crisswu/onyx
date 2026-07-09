# EVA Local Information Intake

This context describes EVA's local, user-specific intake of external information for later retrieval in conversation.

## Language

**Personal Information Pool**:
A local, user-specific collection of externally collected items that EVA can search when answering user questions. The first version is for the current local EVA installation, not a general multi-user Onyx product capability.
_Avoid_: Product-wide news index, shared feed reader

**Feed Subscription**:
An RSS or Atom source that the user asks EVA to maintain as part of the personal information pool. In the first version, EVA manages feed subscriptions through tools, and the subscriptions are stored locally rather than edited by hand in a static config file. A subscription has a default 12-hour fetch cadence and may define its own cadence, with a minimum of 1 hour.
_Avoid_: Static feed config, admin feed record

**Feed Candidate**:
A possible RSS or Atom feed discovered from a user-provided website URL before it becomes a feed subscription. A single candidate can be subscribed automatically; if more than one candidate exists, EVA asks the user which one to subscribe to.
_Avoid_: Scraped source, guessed subscription

**Limited Article Extraction**:
Best-effort extraction of readable article text from the original URL when a feed item only provides a short summary. It excludes login-only content, paywall bypass, JavaScript rendering, CAPTCHA handling, and anti-scraping workarounds.
_Avoid_: Web crawling, scraper bypass, full-site ingestion

**Article Retention Window**:
The period during which collected articles remain in the personal information pool for normal retrieval. The first version keeps articles for 30 days by default, rather than treating the pool as a permanent archive.
_Avoid_: Permanent news archive, indefinite retention

**Saved Article**:
An article that the user explicitly asks EVA to preserve beyond the article retention window. Articles are not saved into long-term EVA knowledge automatically when they expire.
_Avoid_: Auto-archived article, implicit memory

**Local Article Search**:
Retrieval over the personal information pool using article text, metadata, time range, source, and tags. The first version uses keyword or full-text search rather than semantic embeddings. When the user does not specify a time range, local article search defaults to the last 7 days. Search returns at most 10 compact results by default and does not include full article text. Results are ranked by keyword match, freshness, source priority, and number of source appearances.
_Avoid_: Semantic news search, vector article retrieval

**Article Metadata**:
The source-provided and subscription-provided descriptive data used to filter and present RSS articles. The first version does not generate article tags, categories, summaries, or importance scores with an LLM.
_Avoid_: LLM article enrichment, generated importance score

**Article Time**:
The time fields used to interpret an RSS article's recency. `published_at` is the source's publication time; when it is missing, local search and retention use the article's first seen or fetched time while presenting the publication time as unknown.
_Avoid_: Assuming fetch time is publication time

**Local Result Status**:
The freshness and sufficiency signal returned by local article search so EVA can decide whether to answer from the personal information pool or use another source. The RSS tool itself does not call web search.
_Avoid_: Automatic web fallback, blended search result

**RSS Tool Invocation**:
EVA's explicit use of RSS subscription tools when the user asks for RSS information or mentions "RSS" directly. The first version does not rely on broad inference from words like "recent" or "news" to avoid confusing RSS subscription search with other search and memory tools.
_Avoid_: Implicit news search, general current-events trigger

**RSS Subscription Tools**:
The EVA-facing tools that manage and search RSS subscriptions. The first version includes adding, listing, updating RSS subscriptions, and searching RSS articles; article detail retrieval is deferred until the search result shape proves insufficient. Adding a subscription fetches it immediately by default, and updating a subscription may request an immediate fetch.
_Avoid_: Feed reader UI, admin RSS API

**Disabled Feed Subscription**:
A feed subscription that EVA has stopped fetching at the user's request while preserving its record and article source history. In the first version, "delete" or "remove" subscription requests are handled as disabling or archiving, not physical deletion. Local article search excludes disabled feed subscriptions by default unless explicitly asked to include them.
_Avoid_: Hard-deleted feed, erased subscription

**Feed Health**:
The per-subscription state that tells EVA whether RSS fetching is succeeding. Feed health includes the last fetch attempt, last success, last error, consecutive failures, and a status such as active, failing, or disabled; failing subscriptions are not disabled automatically.
_Avoid_: Silent feed failure, auto-disabled feed

**EVA Local Store**:
The local SQLite-backed storage used by EVA-specific personal data in the current installation. RSS subscriptions and articles for the first version live in this store and are accessed through database interfaces under `backend/onyx/db`. RSS data is isolated by EVA user key, matching the existing owner/default data directory and per-user data directory pattern. The first version's scheduled RSS fetch covers only the owner/default store; per-user scheduled fetching is deferred.
_Avoid_: Onyx product database, shared tenant data store

**Article Cluster**:
A deduplicated article record that may have been seen from multiple feed subscriptions or sources. Duplicate feed items are merged into one cluster while preserving source appearances as relevance and heat signals. The first version only auto-merges strong matches such as canonical URL, same-source feed GUID, or content hash matches; title-similar or event-similar articles remain separate.
_Avoid_: Dropped duplicate, repeated article row
