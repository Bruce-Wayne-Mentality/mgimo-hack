"""GigaChat.embed without the network: httpx.MockTransport stands in for the API."""

from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from hse_schedule.gigachat import EMBED_BATCH, OAUTH_URL, GigaChat, GigaChatUnavailable


class FakeApi:
    def __init__(self, *, fail_embeddings: int = 0, status: int = 500) -> None:
        self.oauth_calls = 0
        self.embed_calls = 0
        self.fail_embeddings = fail_embeddings
        self.status = status
        self.batches: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_URL:
            self.oauth_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{self.oauth_calls}", "expires_at": 0})
        self.embed_calls += 1
        if self.fail_embeddings:
            self.fail_embeddings -= 1
            return httpx.Response(self.status, json={"message": "error"})
        body = json.loads(request.content)
        self.batches.append(body["input"])
        # Answer in reverse order: the client must restore the order by «index».
        data = [{"object": "embedding", "index": i, "embedding": [float(len(text)), float(i)]}
                for i, text in reversed(list(enumerate(body["input"])))]
        return httpx.Response(200, json={"object": "list", "data": data, "model": body["model"]})


def client(api: FakeApi) -> GigaChat:
    return GigaChat("c2VjcmV0", transport=httpx.MockTransport(api), embed_model="Embeddings")


class EmbedTests(unittest.TestCase):
    def test_batches_keep_the_original_order(self):
        api = FakeApi()
        texts = [f"фраза номер {'x' * i}" for i in range(EMBED_BATCH + 4)]
        vectors = asyncio.run(client(api).embed(texts))
        self.assertEqual(len(api.batches), 2)
        self.assertEqual([len(b) for b in api.batches], [EMBED_BATCH, 4])
        self.assertEqual([v[0] for v in vectors], [float(len(t)) for t in texts])
        self.assertEqual(api.oauth_calls, 1)  # one token for both batches

    def test_401_authorizes_again_once(self):
        api = FakeApi(fail_embeddings=1, status=401)
        vectors = asyncio.run(client(api).embed(["один", "два"]))
        self.assertEqual(len(vectors), 2)
        self.assertEqual(api.oauth_calls, 2)
        self.assertEqual(api.embed_calls, 2)

    def test_five_failures_open_the_breaker(self):
        api = FakeApi(fail_embeddings=100, status=500)
        giga = client(api)

        async def run() -> None:
            for _ in range(5):
                with self.assertRaises(GigaChatUnavailable):
                    await giga.embed(["текст"])
            before = api.embed_calls
            with self.assertRaises(GigaChatUnavailable) as error:
                await giga.embed(["текст"])
            self.assertEqual(str(error.exception), "circuit open")
            self.assertEqual(api.embed_calls, before)  # no request while the breaker is open

        asyncio.run(run())

    def test_empty_list_makes_no_request(self):
        api = FakeApi()
        self.assertEqual(asyncio.run(client(api).embed([])), [])
        self.assertEqual((api.oauth_calls, api.embed_calls), (0, 0))

    def test_chat_model_can_be_chosen_per_call(self):
        sent = []

        def api(request: httpx.Request) -> httpx.Response:
            if str(request.url) == OAUTH_URL:
                return httpx.Response(200, json={"access_token": "t"})
            sent.append(json.loads(request.content)["model"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "{\"text\": \"ok\"}"}, "finish_reason": "stop"}],
                                             "usage": {"total_tokens": 3}})

        giga = GigaChat("c2VjcmV0", transport=httpx.MockTransport(api), model="GigaChat-2")
        schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
        asyncio.run(giga.chat_json("s", "u", schema))
        result = asyncio.run(giga.chat_json("s", "u", schema, model="GigaChat-2-Max"))
        self.assertEqual(sent, ["GigaChat-2", "GigaChat-2-Max"])
        self.assertEqual(result.model, "GigaChat-2-Max")
        self.assertEqual(giga.model, "GigaChat-2")  # the default for other callers is untouched

    def test_texts_and_key_never_reach_the_log(self):
        api = FakeApi()
        giga = client(api)
        with self.assertLogs("hse_schedule.gigachat", level="INFO") as logs:
            asyncio.run(giga.embed(["секретный вопрос студента"]))
        joined = "\n".join(logs.output)
        self.assertIn("1 texts", joined)
        self.assertNotIn("секретный", joined)
        self.assertNotIn("c2VjcmV0", joined + repr(giga))


if __name__ == "__main__":
    unittest.main()
