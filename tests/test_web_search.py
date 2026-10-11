"""Tavily HTTP contract and search result handling."""

import json
import unittest
from unittest.mock import patch

import httpx

from nanobot.harness.tools.web import WebSearchTool


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_and_result_format(self):
        def handle(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), "https://api.tavily.com/search")
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            self.assertEqual(json.loads(request.content), {
                "query": "测试", "max_results": 10, "search_depth": "basic",
            })
            return httpx.Response(200, json={"results": [{
                "title": "Example", "url": "https://example.com", "content": "摘要",
            }]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("nanobot.harness.tools.web.httpx.AsyncClient", return_value=client):
            result = await WebSearchTool(api_key="test-key").execute("测试", count=20)
        self.assertEqual(result, "Results for: 测试\n\n1. Example\n   https://example.com\n   摘要")

    async def test_empty_results_and_http_error(self):
        for status, expected in [(200, "No results for: query"), (401, "Error:")]:
            with self.subTest(status=status):
                client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(status, json={"results": []})
                ))
                with patch("nanobot.harness.tools.web.httpx.AsyncClient", return_value=client):
                    result = await WebSearchTool(api_key="test-key").execute("query")
                self.assertTrue(result.startswith(expected))

    async def test_key_resolution_and_missing_key(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "env-key"}, clear=True):
            self.assertEqual(WebSearchTool().api_key, "env-key")
            self.assertEqual(WebSearchTool(api_key="config-key").api_key, "config-key")
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(await WebSearchTool().execute("query"),
                             "Error: TAVILY_API_KEY not configured")
