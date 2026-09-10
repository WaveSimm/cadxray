"""mcp SDK 1.x / 2.x 호환 층.

2.0에서 `FastMCP`가 `MCPServer`로 이름만 바뀌었다. `@server.tool()`, `server.run()`,
`Image`의 사용법은 같다. 어느 쪽이 설치돼 있어도 돌아가게 한다.

- 1.x: `from mcp.server.fastmcp import FastMCP, Image`
- 2.x: `from mcp.server.mcpserver import MCPServer, Image`
"""

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as Server  # noqa: F401

    SDK_MAJOR = 2
except ModuleNotFoundError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server, Image  # noqa: F401

    SDK_MAJOR = 1

__all__ = ["Server", "Image", "SDK_MAJOR"]
