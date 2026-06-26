---
name: web-fetch
description: Fetch a web page and return its content as markdown. Use instead of the built-in WebFetch tool which is blocked in this environment.
argument-hint: "<url>"
allowed-tools: Bash(mc-tool-web-fetch *)
---

# /web-fetch

Fetch web content directly from the local machine, bypassing the claude.ai proxy.

## When invoked with a URL

!`mc-tool-web-fetch $ARGUMENTS 2>/dev/null || echo "Fetch failed. Check the URL and try again."`

## Instructions

Present the fetched content to the user. If they asked a question about the page, answer it from the content above.

Options available via Bash:
- `mc-tool-web-fetch <url> --raw` — skip HTML-to-markdown conversion
- `mc-tool-web-fetch <url> --timeout 60` — increase timeout (default 30s)
- `mc-tool-web-fetch <url> --max-size <bytes>` — cap how much of the response is downloaded
- `mc-tool-web-fetch <url> --max-chars <N>` — cap the markdown output length; raise it if a long page came back truncated
- `mc-tool-web-fetch <url> --allow-private` — allow private/loopback IPs
