---
name: web-browsing
description: Search the web and extract information from pages. Use when the user asks a question that requires current information, wants research on a topic, needs documentation lookup, or when you lack the knowledge or recency to answer from training data.
disable-model-invocation: false
---

# Web Browsing

The web is a firehose. The skill is not in finding information — it is in finding the *right* information and knowing when you have enough.

## Tenets

- **Search is iterative.** The first query rarely returns the best result. Every page you read teaches you better terms for the next query.
- **One query, one intent.** A query that asks two questions answers neither well. Split "Python async vs sync performance and Django ORM optimisation" into two searches.
- **Source authority matters.** A blog post from 2019 is not evidence for a 2026 claim. A corporate marketing page is not an independent review. Factor the source into every fact you extract.
- **Corroborate before citing.** A single source is a lead, not a fact. Two independent sources agreeing is a fact. Three is confirmation.

## Leading words

- **Scout** — A broad, exploratory search to map the territory. Before you commit to deep reading, know what exists. Scout searches use wide queries and skim results.
- **Sift** — Evaluate and filter what you found. A result's rank does not equal its value. Sift by relevance, authority, freshness, and independence before deciding what to fetch.
- **Corroborate** — Cross-reference each claim against a second independent source. A claim that cannot be corroborated is a claim you qualify ("According to one source…").

## Phases

### PHASE 1: Plan

**Completion criterion:** the question(s) to search for are written down, each as a separate query string, and the appropriate search backend is chosen.

1. Decompose the user's request into independent questions. Each question gets its own search.
2. For each question, choose the backend by the nature of the answer needed (see [BACKENDS.md](references/BACKENDS.md)).
3. If the question refers to a specific known URL (docs page, blog post, GitHub repo), skip directly to Phase 4 (Extract) — no search needed.

### PHASE 2: Scout

**Completion criterion:** search results returned for every question. At least one result per question looks promising enough to fetch.

1. Run the search with the current best query. Use the `web_search` tool.
2. Read the results through the Sift lens:
   - Does the title match the question?
   - Is the source credible for this domain?
   - Is the date recent enough for the question?
   - Is the snippet self-contained or does it need the full page?
3. If no result is useful, reformulate the query and re-search. Common reformulations: use synonyms, narrow by date range, add a domain filter (`site:python.org`).
4. If reformulation fails twice, change the backend and try a different index.

### PHASE 3: Sift

**Completion criterion:** 1-3 URLs selected per question, each with a stated reason for choosing it (authority, relevance, freshness).

From the scout results, pick what to read deeply:

1. **Prefer primary sources** — official docs, specification pages, authoritative references. Prefer them over blog posts summarising them.
2. **Prefer recent sources** — for time-sensitive topics (API changes, library versions, security advisories), sort by date and use the freshest.
3. **Prefer independent sources** — for claims that matter, pick two sources that do not share an author or publisher.
4. **Prefer specific over general** — a page titled "Async SQLAlchemy 2.0 Session API" is better than "SQLAlchemy Overview".

### PHASE 4: Extract

**Completion criterion:** every selected URL has been fetched and its relevant content extracted. If the content is insufficient, a reason is noted.

1. Fetch each URL with `web_fetch`. Use `extract=True` for HTML pages, `extract=False` for code or raw text.
2. If the result is truncated (the content is longer than the output limit), fetch specific sections by narrowing the URL (anchor link, subpage).
3. If the page is a listing or index, search within the site rather than fetching each link individually.
4. If the fetch fails (404, timeout, blocked), note it and return to the scout results for an alternative URL.

### PHASE 5: Corroborate

**Completion criterion:** every claim that will appear in the answer is supported by at least two independent sources, or is qualified as a single-source claim.

1. For each claim extracted, identify whether it needs corroboration (facts that affect the answer) or is incidental (background colour).
2. For claims that need corroboration, search for a second source. Use a different query or different backend to avoid finding the same page.
3. If corroboration fails, qualify the claim: "According to [source]" rather than stating it as fact.
4. If the corroboration contradicts the first source, investigate the disagreement rather than picking the one you prefer.

## Failure modes

- **First-result bias** — Treating the top-ranked result as the most correct. The top result is the best *marketed* or *linked* page, not necessarily the most accurate. Sift before extracting.
- **Surface skimming** — Reading only snippets, never the full page. Snippets are truncated and decontextualised. Always fetch the page for claims that matter.
- **Source blindness** — Not factoring in who wrote the page and why. A tutorial from a framework's core team outranks a random blog. A vendor's comparison page is marketing, not analysis.
- **Query lock** — Running the same query twice and expecting different results. If scouting yields nothing, reformulate — change terms, backend, or approach before retrying.
- **Overcorroboration** — Spending more time verifying a trivial claim than it's worth. A fact about Python's syntax needs no corroboration. A fact about a library's security vulnerability needs two sources. Curate your corroboration budget.
