# OpenSearch MCP + LLM Integration — Proof of Concept

A working demonstration of integrating the **OpenSearch MCP Server** with an LLM (Google Gemini) using the **Model Context Protocol (MCP)**, enabling natural-language search and interaction with OpenSearch data.

## Architecture
User → Gemini (LLM) → MCP Client → OpenSearch MCP Server → OpenSearch → Results → Gemini → User

- **OpenSearch** — stores and indexes the sample dataset
- **OpenSearch MCP Server** (`opensearch-mcp-server-py`) — exposes OpenSearch operations as MCP tools
- **Custom Python client** (`mcp_client.py`) — connects Gemini to the MCP server via a manual tool-calling loop
- **Gemini** (`gemini-flash-lite-latest`) — interprets natural-language queries and decides which tools to call

## Prerequisites

- Docker and Docker Compose installed
- A free Gemini API key from [Google AI Studio](https://aistudio.google.com) (no credit card required)

## Setup

1. Clone this repository and move into it:
```bash
   git clone <repo-url>
   cd opensearch-mcp-poc
```

2. Set your Gemini API key as an environment variable:
```bash
   export GEMINI_API_KEY="your-api-key-here"
```

3. Start OpenSearch and OpenSearch Dashboards:
```bash
   docker compose up -d
```
   Wait ~30 seconds for OpenSearch to report healthy status.

4. Create the index template and load the sample dataset:
```bash
   curl -X PUT "http://localhost:9200/_index_template/products-template" \
     -H "Content-Type: application/json" \
     -d '{"index_patterns": ["products"], "template": {"mappings": {"properties": {"name": {"type": "text"}, "category": {"type": "text", "fields": {"keyword": {"type": "keyword"}}}, "price": {"type": "float"}, "sales": {"type": "long"}, "rating": {"type": "float"}, "inStock": {"type": "boolean"}}}}}'

   curl -X POST "http://localhost:9200/_bulk" \
     -H "Content-Type: application/x-ndjson" \
     --data-binary @sample_data.json
```

5. Build the MCP client image:
```bash
   docker compose build mcp-client
```

## Running Queries

Run any natural-language query against the OpenSearch data:

```bash
docker compose --profile demo run --rm mcp-client "Show me the top 5 products by sales"
```

Optionally, add a shell alias for convenience:
```bash
alias askmcp="docker compose --profile demo run --rm mcp-client"
askmcp "Find products in the Fitness category"
```

## Example Queries

- `"List all indices in OpenSearch"`
- `"Show me the top 5 products by sales"`
- `"How many products are currently in stock?"`
- `"Find products in the Fitness category"`
- `"Which products have a rating above 4.5?"`
- `"How many products are there in each category?"`
- `"Show me products under $30"`

## Project Structure
opensearch-mcp-poc/
├── docker-compose.yml # OpenSearch, Dashboards, and MCP client services
├── Dockerfile.client # Image for the custom MCP client script
├── mcp_client.py # Core script: Gemini <-> MCP <-> OpenSearch integration
├── requirements.txt # Python dependencies
├── sample_data.json # Sample product dataset (bulk API format)
└── README.md

## Known Limitations

- Complex nested aggregation queries (e.g. computing an average via OpenSearch's native `aggs` syntax) can occasionally cause the LLM to malform the query structure across multiple attempts.
- The LLM sometimes re-verifies a correct empty-result answer instead of trusting it, consuming extra reasoning turns.
- The containerized version is ~2x slower per query than a local virtual-environment run, due to container startup overhead.

## Alternative Approaches Considered

- **Claude Code / Claude Desktop**: requires a Pro/Max subscription or billed API key to connect MCP servers — not usable on the free plan, so Gemini (free tier) was used instead.
- **Native Java/Quarkus MCP server** (via the `quarkus-mcp-server` extension): technically possible, but would require re-implementing OpenSearch tools from scratch rather than using the official, pre-built `opensearch-mcp-server-py`.
