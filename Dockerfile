FROM python:3.12-slim AS build

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.12-slim

RUN useradd --create-home --uid 1000 mcp
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin/ump-x-mcp /usr/local/bin/ump-x-mcp

USER mcp
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"UMP_MCP_PORT\",\"8000\")}/health')"

CMD ["ump-x-mcp"]
