import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { afterEach, test } from "node:test";
import { handler as chat } from "../netlify/functions/chat.mjs";
import { handler as health } from "../netlify/functions/health.mjs";

const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;
let sequence = 0;

function event(body, { method = "POST", ip } = {}) {
  return {
    httpMethod: method,
    body: typeof body === "string" ? body : JSON.stringify(body),
    headers: { "x-nf-client-connection-ip": ip || `test-${++sequence}` },
  };
}

function decode(result) {
  return JSON.parse(result.body);
}

function redisResponse(count, ttl = 60_000) {
  return new Response(JSON.stringify({ result: [count, ttl] }), { status: 200 });
}

function configureRedis() {
  process.env.UPSTASH_REDIS_REST_URL = "https://redis.example.test";
  process.env.UPSTASH_REDIS_REST_TOKEN = "test-redis-token";
}

function configureGroq() {
  process.env.GROQ_API_KEY = "test-groq-key";
  process.env.GROQ_MODEL = "test-model";
}

afterEach(() => {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) delete process.env[key];
  }
  Object.assign(process.env, originalEnv);
  globalThis.fetch = originalFetch;
});

test("chat sends a question and temporary context to Groq without client credentials", async () => {
  configureRedis();
  configureGroq();
  const history = [
    { role: "user", content: "Earlier question" },
    { role: "assistant", content: "Earlier answer" },
  ];
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    if (String(url).startsWith("https://redis.example.test")) return redisResponse(1);
    return new Response(JSON.stringify({ choices: [{ message: { content: "A readable answer." } }] }), {
      status: 200,
    });
  };

  const result = await chat(event({ message: "Follow up", history }, { ip: "203.0.113.20" }));
  assert.equal(result.statusCode, 200);
  assert.equal(decode(result).answer, "A readable answer.");
  assert.equal(requests.length, 2);

  const redisRequest = requests[0];
  assert.equal(redisRequest.url, "https://redis.example.test/");
  assert.equal(redisRequest.options.headers.authorization, "Bearer test-redis-token");
  const redisCommand = JSON.parse(redisRequest.options.body);
  assert.equal(redisCommand[0], "EVAL");
  assert.equal(redisCommand[2], "1");
  assert.equal(redisCommand[3], `aiterminal:rate:v1:${createHash("sha256").update("203.0.113.20").digest("hex")}`);
  assert.equal(redisCommand[3].includes("203.0.113.20"), false);

  const groqRequest = requests[1];
  assert.equal(groqRequest.url, "https://api.groq.com/openai/v1/chat/completions");
  assert.equal(groqRequest.options.headers.authorization, "Bearer test-groq-key");
  const groqBody = JSON.parse(groqRequest.options.body);
  assert.deepEqual(groqBody.messages.slice(1), [
    ...history,
    { role: "user", content: "Follow up" },
  ]);
  assert.equal(groqBody.messages[0].role, "system");
  assert.equal(groqBody.messages[0].content.includes("python_version"), true);
  assert.deepEqual(groqBody.response_format, { type: "json_object" });
  assert.equal("authorization" in event({ message: "hello" }).headers, false);
  assert.equal(JSON.stringify(result).includes("test-groq-key"), false);
});

test("chat returns structured local-action proposals without executing them", async () => {
  configureRedis();
  configureGroq();
  let groqCalls = 0;
  globalThis.fetch = async (url) => {
    if (String(url).startsWith("https://redis.example.test")) return redisResponse(1);
    groqCalls += 1;
    return new Response(
      JSON.stringify({
        choices: [
          {
            message: {
              content: JSON.stringify({
                type: "command",
                message: "I can check the Python version.",
                action: "python_version",
                arguments: {},
              }),
            },
          },
        ],
      }),
      { status: 200 },
    );
  };

  const result = await chat(event({ message: "Check my Python version." }));

  assert.equal(result.statusCode, 200);
  assert.deepEqual(decode(result), {
    answer: "I can check the Python version.",
    proposal: { action: "python_version", arguments: {} },
  });
  assert.equal(groqCalls, 1);
});

test("chat retries without JSON mode when a configured model does not support it", async () => {
  configureRedis();
  configureGroq();
  const groqBodies = [];
  globalThis.fetch = async (url, options) => {
    if (String(url).startsWith("https://redis.example.test")) return redisResponse(1);
    groqBodies.push(JSON.parse(options.body));
    if (groqBodies.length === 1) return new Response("unsupported response format", { status: 400 });
    return new Response(
      JSON.stringify({ choices: [{ message: { content: "A compatible answer." } }] }),
      { status: 200 },
    );
  };

  const result = await chat(event({ message: "hello" }));

  assert.equal(result.statusCode, 200);
  assert.equal(decode(result).answer, "A compatible answer.");
  assert.deepEqual(groqBodies[0].response_format, { type: "json_object" });
  assert.equal("response_format" in groqBodies[1], false);
  assert.deepEqual(groqBodies[0].messages, groqBodies[1].messages);
});

test("chat validates messages, history, body size, and request method", async () => {
  configureRedis();
  configureGroq();
  globalThis.fetch = async () => redisResponse(1);
  assert.equal((await chat(event({ message: "  ", history: [] }))).statusCode, 400);
  assert.equal((await chat(event({ message: "hello", history: null }))).statusCode, 400);
  assert.equal(
    (await chat(event({ message: "hello", history: [{ role: "system", content: "not allowed" }] }))).statusCode,
    400,
  );
  assert.equal(
    (await chat(event({ message: "hello", history: Array(21).fill({ role: "user", content: "x" }) }))).statusCode,
    400,
  );
  assert.equal((await chat(event({ message: "x".repeat(4_001), history: [] }))).statusCode, 400);
  assert.equal(
    (await chat(event(JSON.stringify({ message: "x".repeat(70_000) })))).statusCode,
    413,
  );
  assert.equal((await chat({ httpMethod: "GET" })).statusCode, 405);
  assert.equal((await chat(event("{"))).statusCode, 400);
  assert.equal((await chat({ httpMethod: "POST", body: { message: "hello" } })).statusCode, 400);
});

test("shared Redis counter enforces the limit across handler requests", async () => {
  configureRedis();
  configureGroq();
  let redisCount = 0;
  let groqCalls = 0;
  globalThis.fetch = async (url) => {
    if (String(url).startsWith("https://redis.example.test")) return redisResponse(++redisCount);
    groqCalls += 1;
    return new Response(JSON.stringify({ choices: [{ message: { content: "ok" } }] }), { status: 200 });
  };

  for (let attempt = 0; attempt < 30; attempt += 1) {
    assert.equal((await chat(event({ message: "hello" }, { ip: "198.51.100.10" }))).statusCode, 200);
  }
  const limited = await chat(event({ message: "hello" }, { ip: "198.51.100.10" }));
  assert.equal(limited.statusCode, 429);
  assert.equal(limited.headers["retry-after"], "60");
  assert.equal(groqCalls, 30);
  assert.equal(redisCount, 31);
});

test("chat fails closed if shared rate limiting is not configured or unavailable", async () => {
  configureGroq();
  delete process.env.UPSTASH_REDIS_REST_URL;
  delete process.env.UPSTASH_REDIS_REST_TOKEN;
  let groqCalls = 0;
  globalThis.fetch = async () => {
    groqCalls += 1;
    return new Response("{}", { status: 200 });
  };
  assert.equal((await chat(event({ message: "hello" }))).statusCode, 503);
  assert.equal(
    (
      await chat({
        httpMethod: "POST",
        body: JSON.stringify({ message: "hello" }),
        headers: { "x-forwarded-for": "203.0.113.1" },
      })
    ).statusCode,
    503,
  );
  configureRedis();
  globalThis.fetch = async () => {
    throw new TypeError("private connection detail");
  };
  const result = await chat(event({ message: "hello" }));
  assert.equal(result.statusCode, 503);
  assert.equal(decode(result).error.includes("private connection detail"), false);
  assert.equal(groqCalls, 0);

  globalThis.fetch = async () => new Response(JSON.stringify({ error: "Redis rejected credentials" }), { status: 401 });
  assert.equal((await chat(event({ message: "hello" }))).statusCode, 503);
});

test("chat maps Redis, Groq credentials, model, invalid response, rate limit, and network failures", async () => {
  configureRedis();
  configureGroq();
  const withGroqResponse = (status, body = "{}") => {
    globalThis.fetch = async (url) => {
      if (String(url).startsWith("https://redis.example.test")) return redisResponse(1);
      return new Response(body, { status });
    };
  };

  withGroqResponse(401);
  assert.match(decode(await chat(event({ message: "hello" }))).error, /credentials are invalid/);
  withGroqResponse(404);
  assert.match(decode(await chat(event({ message: "hello" }))).error, /model is unavailable/);
  withGroqResponse(429);
  assert.equal((await chat(event({ message: "hello" }))).statusCode, 429);
  withGroqResponse(200, JSON.stringify({ choices: [] }));
  assert.equal((await chat(event({ message: "hello" }))).statusCode, 502);
  globalThis.fetch = async (url) => {
    if (String(url).startsWith("https://redis.example.test")) return redisResponse(1);
    throw new TypeError("private network error");
  };
  const networkError = await chat(event({ message: "hello" }));
  assert.equal(networkError.statusCode, 502);
  assert.equal(decode(networkError).error.includes("private network error"), false);
});

test("chat handles upstream timeouts and malformed Redis results safely", async () => {
  configureRedis();
  configureGroq();
  globalThis.fetch = async (url) => {
    if (String(url).startsWith("https://redis.example.test")) return redisResponse(1);
    const error = new Error("timeout");
    error.name = "TimeoutError";
    throw error;
  };
  assert.equal((await chat(event({ message: "hello" }))).statusCode, 504);

  globalThis.fetch = async () => new Response(JSON.stringify({ result: "unexpected" }), { status: 200 });
  const result = await chat(event({ message: "hello" }));
  assert.equal(result.statusCode, 503);
  assert.match(decode(result).error, /rate limiting/);
});

test("health endpoint remains a public liveness check", async () => {
  const result = await health({ httpMethod: "GET" });
  assert.equal(result.statusCode, 200);
  assert.deepEqual(decode(result), { status: "ok" });
  assert.equal((await health({ httpMethod: "POST" })).statusCode, 405);
});
