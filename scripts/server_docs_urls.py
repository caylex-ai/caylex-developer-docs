"""
Mapping of server names to MCP (Model Context Protocol) documentation URLs.

Each server maps to a list of URLs that Firecrawl will scrape directly.
Prefer official vendor MCP guides (setup, auth, tools, endpoints). Where the
vendor does not ship an MCP server, use the closest official integration
README or hosted MCP bridge documentation.

To add a new server:
    1. Add an entry with the server name (must match the server registry name exactly)
    2. Provide 1-3 MCP-focused documentation URLs — the most relevant pages only
"""

SERVER_DOCS_URLS: dict[str, list[str]] = {
    "Ahrefs": [
        "https://docs.ahrefs.com/docs/mcp/reference/introduction",
        "https://github.com/ahrefs/ahrefs-mcp-server",
    ],
    "Apify": [
        "https://docs.apify.com/platform/integrations/mcp",
        "https://mcp.apify.com/",
    ],
    "Atlassian": [
        "https://support.atlassian.com/rovo/docs/getting-started-with-the-atlassian-remote-mcp-server/",
        "https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/",
    ],
    "BetterStack": [
        "https://betterstack.com/docs/getting-started/integrations/mcp",
    ],
    "Bitly": [
        "https://dev.bitly.com/bitly-mcp/",
        "https://dev.bitly.com/bitly-mcp/overview/what-is-mcp",
    ],
    "Braintrust": [
        "https://www.braintrust.dev/docs/reference/mcp",
        "https://www.braintrust.dev/docs/kb/configure-mcp-server-with-self-hosted-data-plane",
    ],
    "Bright Data": [
        "https://docs.brightdata.com/mcp-server/overview",
        "https://docs.brightdata.com/mcp-server/tools",
        "https://github.com/brightdata/brightdata-mcp",
    ],
    "Close": [
        "https://help.close.com/v1/docs/en/mcp-server",
    ],
    "Context7": [
        "https://context7.com/docs/installation",
        "https://context7.com/docs/resources/developer",
        "https://github.com/upstash/context7",
    ],
    "Coresignal": [
        "https://docs.coresignal.com/mcp/coresignal-mcp",
        "https://github.com/Coresignal-com/coresignal-mcp",
    ],
    "Datadog": [
        "https://docs.datadoghq.com/bits_ai/mcp_server/",
        "https://docs.datadoghq.com/bits_ai/mcp_server/setup?tab=cursor",
    ],
    "Dropcontact": [
        "https://www.dropcontact.com/mcp-dropcontact",
    ],
    "Elementary Data": [
        "https://docs.elementary-data.com/cloud/mcp/overview",
        "https://docs.elementary-data.com/cloud/mcp/mcp-tools",
    ],
    "Enigma": [
        "https://documentation.enigma.com/guides/ai-mcp",
        "https://documentation.enigma.com/guides/ai-mcp/tools",
        "https://mcp-docs.dev.enigma.com/",
    ],
    "Exa": [
        "https://docs.exa.ai/docs/reference/exa-mcp",
        "https://github.com/exa-labs/exa-mcp-server",
    ],
    "Exa Websets": [
        "https://docs.exa.ai/reference/websets-mcp",
        "https://github.com/exa-labs/websets-mcp-server",
    ],
    "Fellow AI": [
        "https://developers.fellow.ai/reference/mcp-server",
        "https://help.fellow.ai/en/articles/12622641-fellow-s-mcp-server",
    ],
    "Firecrawl": [
        "https://docs.firecrawl.dev/mcp-server",
        "https://github.com/firecrawl/firecrawl-mcp-server",
    ],
    "Fireflies": [
        "https://docs.fireflies.ai/getting-started/docs-mcp-server",
        "https://docs.fireflies.ai/getting-started/mcp-configuration",
        "https://docs.fireflies.ai/mcp-tools/overview",
    ],
    "Fulcra Context": [
        "https://fulcradynamics.github.io/developer-docs/mcp-server/",
        "https://www.fulcradynamics.com/mcp-setup-and-ai-prompts",
    ],
    "Github": [
        "https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/use-the-github-mcp-server",
        "https://github.com/github/github-mcp-server",
    ],
    "Granola": [
        "https://github.com/mishkinf/granola-mcp",
    ],
    "Hunter": [
        "https://hunter.io/blog/hunter-mcp-server-bringing-ai-and-b2b-data-together/",
        "https://hunter.io/api-documentation",
    ],
    "Intercom": [
        "https://developers.intercom.com/docs/guides/mcp",
    ],
    "Klaviyo": [
        "https://developers.klaviyo.com/en/docs/klaviyo_mcp_server",
        "https://www.klaviyo.com/blog/introducing-mcp-server",
    ],
    "LeadFuze": [
        "https://github.com/leadfuze/mcp-server",
    ],
    "Linear": [
        "https://linear.app/docs/mcp",
        "https://developers.linear.app/docs/ai/mcp-server",
    ],
    "Listentic": [
        "https://www.remote-mcp.com/servers/listenetic",
    ],
    "Needle": [
        "https://docs.needle-ai.com/docs/guides/mcp/needle-mcp-server/",
        "https://docs.needle-ai.com/docs/mcp/",
        "https://github.com/needle-ai/needle-mcp",
    ],
    "Neon": [
        "https://neon.tech/docs/ai/neon-mcp-server",
        "https://neon.tech/docs/ai/connect-mcp-clients-to-neon",
        "https://github.com/neondatabase-labs/mcp-server-neon",
    ],
    "Notion": [
        "https://developers.notion.com/docs/mcp",
        "https://developers.notion.com/docs/get-started-with-mcp",
        "https://github.com/makenotion/notion-mcp-server",
    ],
    "Octagon": [
        "https://docs.octagonagents.com/guide/mcp-server.html",
        "https://github.com/OctagonAI/octagon-mcp-server",
    ],
    "Polar Signals": [
        "https://www.polarsignals.com/docs/mcp",
        "https://www.polarsignals.com/blog/posts/2025/07/17/the-mcp-for-performance-engineering/",
    ],
    "Posthog": [
        "https://posthog.com/docs/model-context-protocol",
        "https://github.com/PostHog/mcp",
    ],
    "Postman": [
        "https://learning.postman.com/docs/developer/postman-api/postman-mcp-server/set-up-postman-mcp-server",
        "https://learning.postman.com/docs/postman-ai/mcp-servers/overview",
    ],
    "Scorecard": [
        "https://docs.scorecard.io/features/mcp",
        "https://github.com/scorecard-ai/scorecard-mcp",
    ],
    "Sentry": [
        "https://docs.sentry.io/ai/mcp",
    ],
    "Shopify": [
        "https://shopify.dev/docs/apps/build/devmcp",
        "https://github.com/Shopify/dev-mcp",
        "https://shopify.dev/docs/agents/checkout/mcp",
    ],
    "Short.io": [
        "https://docs.short.io/articles/integrations-and-extensions/direct-integrations/how-to-integrate-and-use-short.io-with-your-mcp-enabled-service",
        "https://blog.short.io/new-mcp-support/",
    ],
    "Simplescraper": [
        "https://simplescraper.io/docs/mcp-server",
    ],
    "Tavily": [
        "https://docs.tavily.com/guides/mcp",
        "https://github.com/tavily-ai/tavily-mcp",
    ],
    "Webflow": [
        "https://developers.webflow.com/mcp",
        "https://developers.webflow.com/mcp/reference/getting-started",
        "https://github.com/webflow/mcp-server",
    ],
}
