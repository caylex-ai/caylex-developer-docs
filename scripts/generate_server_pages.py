#!/usr/bin/env python3
"""
Generate Mintlify MDX documentation pages for servers in the Caylex server registry.

Usage:
    python generate_server_pages.py --api-base-url https://api.caylex.ai --token <TOKEN>
    python generate_server_pages.py --api-base-url https://api.caylex.ai --token <TOKEN> --enrich-llm

Flags:
    --overwrite <name>   Regenerate a specific server's page even if it already exists
    --overwrite-all      Regenerate all pages from scratch
    --enrich-llm         Use Firecrawl + Claude to generate richer descriptions and use cases
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import jinja2
import requests

from server_docs_urls import SERVER_DOCS_URLS
from server_related import SERVER_RELATED

# Paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
OUTPUT_DIR = DOCS_ROOT / "server-catalog"
DOCS_JSON = DOCS_ROOT / "docs.json"

# OAuth guides that exist (for cross-linking)
OAUTH_GUIDES_DIR = DOCS_ROOT / "oauth-guides"

# LLM enrichment cache
LLM_CACHE_DIR = SCRIPT_DIR / ".enrichment-cache"


def slugify(name: str) -> str:
    """Convert a server name to a URL-friendly slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug


def sanitize_mdx(text: str) -> str:
    """
    Escape characters that break MDX parsing.

    MDX treats <word>, {expression}, and @ inside angle brackets as JSX.
    This function escapes them so they render as plain text.
    """
    if not text:
        return text

    # Escape curly braces that MDX would interpret as JSX expressions.
    # First: wrap {{ ... }} template tags in backticks
    text = re.sub(r"\{\{(.*?)\}\}", r"`{{\1}}`", text)
    # Then: escape remaining bare { } outside of backtick spans
    # Split on backtick-delimited sections to avoid escaping inside code
    parts = re.split(r"(`[^`]*`)", text)
    for i, part in enumerate(parts):
        if not part.startswith("`"):
            parts[i] = part.replace("{", "\\{").replace("}", "\\}")
    text = "".join(parts)

    # Escape <word> patterns that look like JSX tags (but not valid Mintlify components).
    # Valid components: <Accordion>, <AccordionGroup>, <Tip>, <Info>, <Note>, <Warning>,
    # <Steps>, <Step>, <Frame>, <Card>, <CardGroup>, <Tabs>, <Tab>, <CodeGroup>
    VALID_MDX_TAGS = {
        "Accordion", "AccordionGroup", "Tip", "Info", "Note", "Warning",
        "Steps", "Step", "Frame", "Card", "CardGroup", "Tabs", "Tab",
        "CodeGroup", "Expandable", "ResponseField", "ParamField",
        "sup", "sub", "br", "img", "a", "code", "pre", "em", "strong",
    }

    def _escape_tag(match: re.Match) -> str:
        full_tag = match.group(1)
        # Extract just the tag name (first word, ignoring attributes)
        tag_name = re.match(r"/?\w+", full_tag)
        if tag_name:
            base_tag = tag_name.group(0).lstrip("/")
            if base_tag in VALID_MDX_TAGS:
                return match.group(0)
        # Escape the angle brackets
        return match.group(0).replace("<", "&lt;").replace(">", "&gt;")

    # Match <word...> patterns, including </word> closing tags
    text = re.sub(r"<(/?\w[^>]*)>", _escape_tag, text)

    # Escape bare @ inside angle brackets (e.g., <user@email.com>)
    # These were already caught above since <user@email.com> matches <word...>

    # Convert markdown lists to HTML lists.
    # Raw markdown lists (- item) inside JSX components like <Accordion> break MDX.
    def _md_lists_to_html(t: str) -> str:
        lines = t.split("\n")
        result = []
        in_list = False
        for line in lines:
            stripped = line.strip()
            if re.match(r"^[-*]\s", stripped):
                if not in_list:
                    result.append("<ul>")
                    in_list = True
                item_text = re.sub(r"^[-*]\s+", "", stripped)
                result.append(f"<li>{item_text}</li>")
            else:
                if in_list:
                    result.append("</ul>")
                    in_list = False
                result.append(line)
        if in_list:
            result.append("</ul>")
        return "\n".join(result)

    text = _md_lists_to_html(text)

    return text


def sanitize_tools(tools: list[dict]) -> list[dict]:
    """Sanitize all text fields in tool dicts for MDX safety."""
    sanitized = []
    for tool in tools:
        t = dict(tool)
        if t.get("description"):
            t["description"] = sanitize_mdx(t["description"])
        if t.get("params"):
            t["params"] = [
                {**p, "description": sanitize_mdx(p.get("description", ""))}
                for p in t["params"]
            ]
        sanitized.append(t)
    return sanitized


def sanitize_enrichment(enrichment: dict) -> dict:
    """Sanitize all text fields in LLM enrichment dict for MDX safety."""
    if not enrichment:
        return enrichment
    result = dict(enrichment)
    if result.get("overview"):
        result["overview"] = sanitize_mdx(result["overview"])
    if result.get("api_notes"):
        result["api_notes"] = [sanitize_mdx(n) for n in result["api_notes"]]
    return result


def get_existing_oauth_guides() -> set[str]:
    """Return set of slugs that have an oauth-guide page."""
    if not OAUTH_GUIDES_DIR.is_dir():
        return set()
    return {p.stem for p in OAUTH_GUIDES_DIR.iterdir() if p.suffix == ".mdx"}


def fetch_all_servers(base_url: str, token: str) -> list[dict]:
    """Paginate through GET /api/v1/server-registry/ and return all servers."""
    headers = {"Authorization": f"Bearer {token}"}
    servers = []
    cursor = None

    while True:
        params: dict = {"size": 100}
        if cursor:
            params["cursor"] = cursor

        resp = requests.get(
            f"{base_url}/api/v1/server-registry/",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        servers.extend(items)

        meta = data.get("meta", {})
        if meta.get("has_next") and meta.get("next_cursor"):
            cursor = meta["next_cursor"]
        else:
            break

    return servers


def fetch_tools(base_url: str, token: str, server_id: str) -> list[dict]:
    """Fetch tools for a server registry entry. Returns empty list on 404."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"{base_url}/api/v1/server-registry/{server_id}/tools",
        headers=headers,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    data = resp.json()
    return data.get("tools", [])


def extract_oauth_scopes(auth_configs: list[dict] | None) -> list[str]:
    """Extract OAuth scopes from auth_configs list."""
    if not auth_configs:
        return []
    for config in auth_configs:
        oauth = config.get("oauth_config")
        if oauth and oauth.get("scopes"):
            return oauth["scopes"]
    return []


def extract_auth_details(auth_configs: list[dict] | None) -> dict:
    """
    Extract non-OAuth auth configuration details from auth_configs.

    Returns dict with:
        - headers: list[dict] with {name, prefix} for HEADER auth
        - path_params: list[str] for PATH auth
        - query_params: list[str] for QUERY auth
    """
    details: dict = {"headers": [], "path_params": [], "query_params": []}
    if not auth_configs:
        return details

    for config in auth_configs:
        method = (config.get("auth_method") or "").upper()

        if method == "HEADER":
            header_config = config.get("config") or config.get("header_config") or {}
            items = header_config.get("items", [])
            if not items and isinstance(header_config, list):
                items = header_config
            for item in items:
                name = item.get("header_name", "")
                prefix = item.get("header_value_prefix", "")
                if name:
                    details["headers"].append({"name": name, "prefix": prefix})

        elif method == "PATH":
            path_config = config.get("config") or config.get("path_config") or {}
            items = path_config.get("items", [])
            if not items and isinstance(path_config, list):
                items = path_config
            for item in items:
                name = item.get("path_param_name", "")
                if name:
                    details["path_params"].append(name)

        elif method == "QUERY":
            query_config = config.get("config") or config.get("query_config") or {}
            items = query_config.get("items", [])
            if not items and isinstance(query_config, list):
                items = query_config
            for item in items:
                name = item.get("query_param_name", "")
                if name:
                    details["query_params"].append(name)

    return details


# ---------------------------------------------------------------------------
# LLM enrichment: Firecrawl + Claude
# ---------------------------------------------------------------------------

def _cache_key(server_name: str, tool_names: list[str]) -> str:
    """Deterministic cache key based on server name and its tool set."""
    payload = json.dumps({"name": server_name, "tools": sorted(tool_names)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_cached_enrichment(server_name: str, tool_names: list[str]) -> dict | None:
    """Return cached LLM enrichment if it exists, else None."""
    if not LLM_CACHE_DIR.is_dir():
        return None
    key = _cache_key(server_name, tool_names)
    cache_file = LLM_CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            if data.get("server_name") == server_name:
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def save_cached_enrichment(server_name: str, tool_names: list[str], enrichment: dict) -> None:
    """Persist LLM enrichment to disk."""
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(server_name, tool_names)
    cache_file = LLM_CACHE_DIR / f"{key}.json"
    enrichment["server_name"] = server_name
    cache_file.write_text(json.dumps(enrichment, indent=2))


def firecrawl_scrape_url(url: str, api_key: str) -> str:
    """
    Scrape a single URL via Firecrawl and return its markdown content.
    """
    resp = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "url": url,
            "formats": ["markdown"],
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"    Warning: Firecrawl scrape failed for {url} ({resp.status_code})")
        return ""

    data = resp.json()
    if not data.get("success"):
        return ""

    result = data.get("data", {})
    title = result.get("metadata", {}).get("title", "")
    markdown = result.get("markdown", "")
    if markdown:
        # Truncate very long pages to keep Claude prompt reasonable
        return f"# {title}\nSource: {url}\n\n{markdown[:4000]}"
    return ""


def firecrawl_scrape_urls(urls: list[str], api_key: str) -> str:
    """
    Scrape multiple URLs and return concatenated markdown content.
    """
    chunks = []
    for url in urls:
        chunk = firecrawl_scrape_url(url, api_key)
        if chunk:
            chunks.append(chunk)
    return "\n\n---\n\n".join(chunks)


def enrich_with_llm(
    server_name: str,
    server_description: str,
    tool_names: list[str],
    scraped_docs: str,
    anthropic_api_key: str,
) -> dict:
    """
    Call Claude API to extract supplementary context from official docs.

    Returns dict with keys:
        - overview: str (key capabilities/features not covered by the description)
        - api_notes: list[str] (rate limits, pagination, important caveats)
        - prerequisites: list[str] (account requirements, permissions, setup steps)
        - tool_categories: dict[str, list[str]] (category_name -> [tool_names])
    """
    tools_list = "\n".join(f"- {t}" for t in tool_names)

    prompt = f"""You are a technical writer for the Caylex platform's MCP server catalog.
Caylex is a platform that connects AI agents to external services via MCP (Model Context Protocol)
servers. Users add servers to their Caylex projects, authenticate via OAuth or headers, path or query based parameters, and then
their AI agents can invoke the server's tools through Caylex Navigators.

The server registry already provides a description, subtitle, and tool names/descriptions.
Your job is to extract SUPPLEMENTARY context from the official documentation that helps Caylex
users understand how this server works within the Caylex ecosystem.

IMPORTANT RULES:
- Do NOT mention Cursor, Claude Desktop, VS Code, Windsurf, or any other MCP client.
- Do NOT include setup instructions for other platforms (e.g., "add to claude_desktop_config.json").
- Do NOT include any server endpoint URLs, MCP URLs, SSE URLs, or remote connection addresses (e.g., "https://mcp.example.com/mcp"). Caylex handles the connection — users do not need to know the endpoint.
- Frame everything from the perspective of a Caylex user adding this server to their project.
- Focus on what the tools do, what data they access, and any API constraints users should know.
- Add any extra configuration that the server might need. Examples (not a comprehensive list) might include query parameters that user can add to the server URL
  to enable feature set, path parameters that user can set, or templated fields in the domain name itself.
SERVER NAME: {server_name}
EXISTING DESCRIPTION: {server_description}
TOOLS:
{tools_list}

OFFICIAL DOCUMENTATION:
{scraped_docs[:8000] if scraped_docs else "(no documentation available)"}

Generate a JSON object with ONLY these fields:
1. "overview": A paragraph (3-6 sentences) that serves as the SOLE description shown on the documentation
   page. It must semantically incorporate the meaning of the EXISTING DESCRIPTION above while enriching
   it with additional context from the official documentation. Write it as a polished, self-contained
   introduction — do not assume the existing description will be shown separately. Focus on what this
   server enables within Caylex and what AI agents can do with it. This field must ALWAYS be non-empty.
2. "api_notes": An array of 2-4 short strings about important details Caylex users should know:
   rate limits, required permissions/scopes, pagination behavior, known limitations, etc.
   Only include notes actually mentioned in the documentation. Return an empty array if none found.
3. "prerequisites": An array of 1-3 short strings describing what a user needs BEFORE connecting
   this server in Caylex: required account tier (e.g., "Requires a Pro plan or higher"), admin
   permissions (e.g., "Workspace admin access required"), API access that must be enabled in the
   vendor dashboard, or other setup steps. Only include prerequisites actually mentioned in the
   documentation. Return an empty array if none found.
4. "server_configuration": An array of objects describing query parameters, path parameters, or
   URL template fields that users can set when adding the server URL in Caylex. Each object should
   have: "param" (the parameter name), "type" ("query", "path", or "url_template"),
   "description" (what it does), and "example" (an example value). This is especially important
   for parameters that activate specific tool sets or feature modes (e.g., "&groups=search" to
   enable only search tools, "&pro=1" to enable pro mode). Return an empty array if none found.
5. "tool_categories": A JSON object mapping category names (e.g., "Read", "Write", "Search", "Admin")
   to arrays of tool names from the list above. Group tools by their function. Only include
   categories that have tools.

Return ONLY valid JSON, no markdown fencing or explanation."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"].strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        return json.loads(text)
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as exc:
        print(f"    Warning: Claude enrichment failed for '{server_name}': {exc}")
        return {}


def get_llm_enrichment(
    server_name: str,
    server_description: str,
    tool_names: list[str],
    firecrawl_api_key: str,
    anthropic_api_key: str,
) -> dict:
    """
    Full enrichment pipeline: check cache → Firecrawl (official docs) → Claude → cache result.
    """
    # Check cache first
    cached = load_cached_enrichment(server_name, tool_names)
    if cached:
        print(f"    Using cached LLM enrichment for '{server_name}'")
        return cached

    # Look up exact documentation URLs for this server
    doc_urls = SERVER_DOCS_URLS.get(server_name)
    if not doc_urls:
        print(f"    Warning: No documentation URLs mapped for '{server_name}', skipping LLM enrichment")
        return {}

    # Scrape official documentation pages
    print(f"    Scraping {len(doc_urls)} official doc pages for '{server_name}'...")
    scraped = firecrawl_scrape_urls(doc_urls, firecrawl_api_key)

    if not scraped:
        print(f"    Warning: No documentation found for '{server_name}'")
        return {}

    # Generate enriched content
    print(f"    Generating enriched content with Claude...")
    enrichment = enrich_with_llm(
        server_name, server_description, tool_names, scraped, anthropic_api_key
    )
    if enrichment:
        save_cached_enrichment(server_name, tool_names, enrichment)

    # Rate limit: be polite to both APIs
    time.sleep(1)

    return enrichment


def build_template_context(
    server: dict,
    tools: list[dict],
    slug: str,
    oauth_guides: set[str],
    enrichment: dict | None = None,
    app_domain: str = "app.caylex.ai",
    server_logo_map: dict[str, str] | None = None,
) -> dict:
    """Build the Jinja2 template context for a server."""
    # Sanitize server description for MDX (it's rendered as body text)
    server = dict(server)  # shallow copy to avoid mutating original
    if server.get("description"):
        server["description"] = sanitize_mdx(server["description"])

    # Normalize auth methods to uppercase (API may return lowercase enum values)
    raw_methods = server.get("auth_methods") or []
    auth_methods = [m.upper() if isinstance(m, str) else str(m).upper() for m in raw_methods]
    categories = []
    labels = server.get("labels")
    if labels and isinstance(labels.get("categories"), list):
        categories = [c for c in labels["categories"] if c and c.strip()]

    has_oauth = "OAUTH" in auth_methods
    has_no_auth = "NO_AUTH" in auth_methods or "NONE" in auth_methods or len(auth_methods) == 0
    oauth_scopes = extract_oauth_scopes(server.get("auth_configs"))
    auth_details = extract_auth_details(server.get("auth_configs"))
    has_oauth_guide = slug in oauth_guides

    return {
        "server": server,
        "tools": tools,
        "slug": slug,
        "categories": categories,
        "auth_methods": auth_methods,
        "has_oauth": has_oauth,
        "has_no_auth": has_no_auth,
        "oauth_scopes": oauth_scopes,
        "has_oauth_guide": has_oauth_guide,
        "auth_details": auth_details,
        "enrichment": enrichment or {},
        "doc_urls": SERVER_DOCS_URLS.get(server.get("name", ""), []),
        "health_status": server.get("health_status"),
        "related_servers": [
            {"name": name, "slug": slugify(name), "logo_url": (server_logo_map or {}).get(name)}
            for name in SERVER_RELATED.get(server.get("name", ""), [])
        ],
        "app_domain": app_domain,
    }


def update_docs_json(page_paths: list[str]) -> None:
    """Update docs.json to include a 'Server Catalog' navigation group."""
    with open(DOCS_JSON) as f:
        config = json.load(f)

    tabs = config.get("navigation", {}).get("tabs", [])
    if not tabs:
        print("Warning: No tabs found in docs.json, skipping navigation update.")
        return

    groups = tabs[0].get("groups", [])

    # Find existing Server Catalog group or determine insert position
    catalog_index = None
    for i, group in enumerate(groups):
        if group.get("group") == "Server Catalog":
            catalog_index = i
            break

    catalog_group = {
        "group": "Server Catalog",
        "pages": sorted(page_paths),
    }

    if catalog_index is not None:
        groups[catalog_index] = catalog_group
    else:
        # Insert before "OAuth Guides" if it exists, otherwise append
        oauth_index = None
        for i, group in enumerate(groups):
            if group.get("group") == "OAuth Guides":
                oauth_index = i
                break

        if oauth_index is not None:
            groups.insert(oauth_index, catalog_group)
        else:
            groups.append(catalog_group)

    with open(DOCS_JSON, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generate Mintlify docs for Caylex server registry entries."
    )
    parser.add_argument(
        "--api-base-url",
        required=True,
        help="Base URL of the Caylex analytics API (e.g., https://api.caylex.ai)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CAYLEX_API_TOKEN"),
        help="Platform access token (or set CAYLEX_API_TOKEN env var)",
    )
    parser.add_argument(
        "--overwrite",
        metavar="SERVER_NAME",
        help="Regenerate page for a specific server (by name), even if it exists",
    )
    parser.add_argument(
        "--overwrite-all",
        action="store_true",
        help="Regenerate all server pages from scratch",
    )
    parser.add_argument(
        "--enrich-llm",
        action="store_true",
        help="Use Firecrawl + Claude to generate richer descriptions and use cases",
    )
    parser.add_argument(
        "--firecrawl-api-key",
        default=os.environ.get("FIRECRAWL_API_KEY"),
        help="Firecrawl API key (or set FIRECRAWL_API_KEY env var)",
    )
    parser.add_argument(
        "--anthropic-api-key",
        default=os.environ.get("ANTHROPIC_API_KEY"),
        help="Anthropic API key for Claude (or set ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.token:
        print("Error: --token or CAYLEX_API_TOKEN env var is required.", file=sys.stderr)
        sys.exit(1)

    base_url = args.api_base_url.rstrip("/")

    # Derive app domain from API base URL
    app_domain = "app.caylex.dev" if "caylex.dev" in base_url else "app.caylex.ai"

    # LLM enrichment validation
    firecrawl_key = args.firecrawl_api_key
    anthropic_key = args.anthropic_api_key
    if args.enrich_llm:
        if not firecrawl_key or not anthropic_key:
            print(
                "Error: --enrich-llm requires --firecrawl-api-key and --anthropic-api-key "
                "(or FIRECRAWL_API_KEY and ANTHROPIC_API_KEY env vars).",
                file=sys.stderr,
            )
            sys.exit(1)
        print("LLM enrichment enabled (Firecrawl + Claude). Cache dir:", LLM_CACHE_DIR)

    # Set up Jinja2
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("server_page.mdx.j2")

    # Fetch data
    print("Fetching servers from API...")
    servers = fetch_all_servers(base_url, args.token)
    print(f"Found {len(servers)} servers.")

    # Build name -> logo_url map for related server icons
    server_logo_map: dict[str, str] = {}
    for s in servers:
        name = s.get("name")
        logo = s.get("logo_url")
        if name and logo:
            server_logo_map[name] = logo

    oauth_guides = get_existing_oauth_guides()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Track generated pages and slug collisions
    used_slugs: dict[str, str] = {}  # slug -> server name
    page_paths: list[str] = []
    generated = 0
    skipped = 0

    for server in servers:
        name = server.get("name")
        if not name:
            print(f"  Skipping server with no name (id={server.get('id')})")
            skipped += 1
            continue

        slug = slugify(name)

        # Handle slug collisions
        if slug in used_slugs:
            original = slug
            counter = 2
            while slug in used_slugs:
                slug = f"{original}-{counter}"
                counter += 1
            print(f"  Warning: slug collision for '{name}', using '{slug}' instead of '{original}'")

        used_slugs[slug] = name
        output_path = OUTPUT_DIR / f"{slug}.mdx"
        page_path = f"server-catalog/{slug}"

        # Check if we should generate this page
        if output_path.exists() and not args.overwrite_all:
            if args.overwrite and args.overwrite.lower() == name.lower():
                pass  # proceed with overwrite
            else:
                page_paths.append(page_path)
                skipped += 1
                continue

        # Fetch tools from server registry
        server_id = server.get("id")
        tools = fetch_tools(base_url, args.token, server_id) if server_id else []

        # LLM enrichment (Firecrawl + Claude)
        enrichment = None
        if args.enrich_llm:
            tool_names = [t.get("name", "") for t in tools if t.get("name")]
            enrichment = get_llm_enrichment(
                name,
                server.get("description", ""),
                tool_names,
                firecrawl_key,
                anthropic_key,
            )

        # Sanitize dynamic content for MDX safety
        tools = sanitize_tools(tools)
        if enrichment:
            enrichment = sanitize_enrichment(enrichment)

        # Build context and render
        context = build_template_context(server, tools, slug, oauth_guides, enrichment, app_domain, server_logo_map)
        content = template.render(**context)

        output_path.write_text(content)
        page_paths.append(page_path)
        generated += 1
        print(f"  Generated: {output_path.name}")

    # Update docs.json navigation
    update_docs_json(page_paths)

    print(f"\nDone. Generated: {generated}, Skipped: {skipped}, Total: {len(servers)}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Updated: {DOCS_JSON}")


if __name__ == "__main__":
    main()
