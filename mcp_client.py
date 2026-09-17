"""
OpenSearch MCP + Gemini LLM Integration - POC Script
Flow: User query -> Gemini LLM -> MCP Client -> OpenSearch MCP Server -> OpenSearch -> Results -> Gemini -> User
"""
import asyncio
import os
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google import genai
from google.genai import types
from google.genai.errors import ClientError

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENSEARCH_PYTHON = os.environ.get("OPENSEARCH_PYTHON", "python")
MAX_TURNS = 12

server_params = StdioServerParameters(
    command=OPENSEARCH_PYTHON,
    args=["-m", "mcp_server_opensearch"],
    env={
        "OPENSEARCH_URL": os.environ.get("OPENSEARCH_URL", "http://localhost:9200"),
        "OPENSEARCH_NO_AUTH": "true",
        "OPENSEARCH_ENABLED_TOOLS": "ListIndexTool,IndexMappingTool,SearchIndexTool,CountTool,GenericOpenSearchApiTool",
    },
)

UNSUPPORTED_KEYS = {
    "$schema", "additionalProperties", "title", "examples",
    "default", "$id", "definitions", "$defs", "const",
}

def clean_schema(schema):
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k not in UNSUPPORTED_KEYS}
    elif isinstance(schema, list):
        return [clean_schema(item) for item in schema]
    return schema

def get_function_call(response):
    for part in response.candidates[0].content.parts:
        if getattr(part, "function_call", None):
            return part.function_call
    return None

def get_text(response):
    parts = response.candidates[0].content.parts
    texts = [p.text for p in parts if getattr(p, "text", None)]
    return "\n".join(texts) if texts else None

SYSTEM_INSTRUCTION = (
    "You are responding in a plain terminal window that does not render markdown. "
    "Never use asterisks, bold, italics, or headers. Use plain text only. "
    "For lists, use plain dashes (-) or numbers (1., 2.) with no other symbols."
)

def call_gemini_with_retry(client, contents, tools):
    for attempt in range(4):
        try:
            return client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0,
                    tools=[tools] if tools else None,
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
            )
        except ClientError as e:
            if e.code == 429 and attempt < 3:
                wait = 20
                print(f"[RATE LIMIT] Hit quota, waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                raise

async def run_query(query: str):
    print(f"\n{'='*70}")
    print(f"USER QUERY: {query}")
    print('='*70)

    async with stdio_client(server_params, errlog=open(os.devnull, "w")) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            print(f"[MCP] {len(tools_result.tools)} tools discovered: "
                  f"{[t.name for t in tools_result.tools]}\n")

            function_declarations = [
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description or "",
                    parameters=clean_schema(t.inputSchema),
                )
                for t in tools_result.tools
            ]
            gemini_tools = types.Tool(function_declarations=function_declarations)
            client = genai.Client(api_key=GEMINI_API_KEY)
            contents = [types.Content(role="user", parts=[types.Part(text=query)])]

            for turn in range(MAX_TURNS):
                response = call_gemini_with_retry(client, contents, gemini_tools)

                fn = get_function_call(response)
                if not fn:
                    text = get_text(response)
                    print(f"FINAL LLM RESPONSE:\n{text}\n")
                    return

                print(f"[LLM DECISION - turn {turn+1}] Calling tool: {fn.name}")
                print(f"[LLM DECISION - turn {turn+1}] Arguments: {dict(fn.args)}\n")

                tool_result = await session.call_tool(fn.name, dict(fn.args))
                result_text = "\n".join(
                    c.text for c in tool_result.content if hasattr(c, "text")
                )
                print(f"[OPENSEARCH RESULT - turn {turn+1}]\n{result_text[:800]}\n")

                contents.append(response.candidates[0].content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name=fn.name, response={"result": result_text}
                    ))]
                ))
                time.sleep(1)

            # Force a final answer using only the context gathered so far, no more tool calls
            final_response = client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0,
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
            )
            final_text = get_text(final_response) or "(Could not determine a final answer from the gathered data)"
            print(f"FINAL LLM RESPONSE:\n{final_text}\n")

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "List all indices in OpenSearch"
    asyncio.run(run_query(q))
