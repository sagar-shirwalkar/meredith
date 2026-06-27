# Search Backend Selection

Consult during PHASE 1 (Plan) to choose the right backend for each query.

## Brave Search

| Feature | Detail |
|---|---|
| Index type | General web index (independent) |
| Free tier | 2,000 queries/month |
| Best for | General knowledge, current events, documentation lookups |
| Weakness | Less structured results, no citation metadata |

Use Brave for:
- "What is the latest version of Python?"
- "FastAPI file upload example"
- "How does asyncio.gather handle exceptions?"

## Tavily

| Feature | Detail |
|---|---|
| Index type | AI-optimised, citation-focused |
| Free tier | 1,000 queries/month |
| Best for | Research, fact-checking, questions requiring cited answers |
| Weakness | Smaller index than Brave, less useful for niche technical queries |

Use Tavily for:
- "What are the trade-offs between Pydantic v1 and v2?"
- Research topics where you need structured answers with citations
- Topics where source attribution matters in the answer

## Exa (neural search)

| Feature | Detail |
|---|---|
| Index type | Neural/semantic (embeddings-based) |
| Free tier | Limited trials |
| Best for | Semantic similarity, finding conceptually related content |
| Weakness | Less effective for precise keyword lookups |

Use Exa for:
- "Find content similar to this blog post about async testing"
- Conceptual exploration where keywords are insufficient
- Finding related research papers or technical analyses
