"""
Web search tool using DuckDuckGo Instant Answer API.
No API key required. Returns organic search results as plain text.
"""

import json
import urllib.parse
import urllib.request


# Max results to return from a single search
DEFAULT_MAX_RESULTS = 5
# Request timeout in seconds
_REQUEST_TIMEOUT = 15


def search_web(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> str:
    """
    Search the web using DuckDuckGo and return a formatted list of results.

    Uses DuckDuckGo's free JSON API — no API key needed.
    Results include title, URL, and a short snippet per hit.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default: 5, max: 10).

    Returns:
        Formatted string with numbered results, or an error message.
    """
    max_results = max(1, min(max_results, 10))

    encoded_query = urllib.parse.quote_plus(query)
    url = (
        f"https://api.duckduckgo.com/?q={encoded_query}"
        f"&format=json&no_html=1&skip_disambig=1"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CAWL-Agent/0.2 (local AI agent)"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")

        data = json.loads(raw)

    except urllib.error.URLError as e:
        return f"[ERROR] Network error during search: {e}"
    except json.JSONDecodeError as e:
        return f"[ERROR] Failed to parse DuckDuckGo response: {e}"
    except Exception as e:
        return f"[ERROR] search_web failed: {e}"

    results: list[str] = []

    # 1. Instant Answer (Abstract)
    abstract = data.get("Abstract", "").strip()
    abstract_url = data.get("AbstractURL", "").strip()
    if abstract:
        results.append(f"[Instant Answer]\n{abstract}\n{abstract_url}")

    # 2. Related topics / organic results
    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break
        # Flat result
        if "FirstURL" in topic and "Text" in topic:
            results.append(f"- {topic['Text']}\n  {topic['FirstURL']}")
        # Nested section (e.g. "See also")
        elif "Topics" in topic:
            for sub in topic["Topics"]:
                if len(results) >= max_results:
                    break
                if "FirstURL" in sub and "Text" in sub:
                    results.append(f"- {sub['Text']}\n  {sub['FirstURL']}")

    if not results:
        return (
            f"No results found for '{query}'.\n"
            "Tip: try a more specific query or check your internet connection."
        )

    header = f"Search results for: \"{query}\" ({len(results)} found)\n{'=' * 50}"
    return header + "\n\n" + "\n\n".join(results)
