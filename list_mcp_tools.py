import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                description = (tool.description or "").strip()
                first_line = description.splitlines()[0] if description else " AUCUNE DESCRIPTION"
                print(f" {tool.name}\n   {first_line}\n   parametres : {list(tool.input_schema['properties'])}\n")
            result = await session.call_tool("validate_k8s_yaml", {"yaml_text": "apiVersion: v1\nkind: Pod\n"})
            print("Test d'appel :", result.content[0].text)

asyncio.run(main())