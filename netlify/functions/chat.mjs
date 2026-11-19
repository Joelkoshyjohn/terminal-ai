import { createHash } from "node:crypto";

const MAX_BODY_BYTES = 64 * 1024;
const MAX_QUESTION_LENGTH = 4_000;
const MAX_HISTORY_MESSAGES = 20;
const MAX_HISTORY_MESSAGE_LENGTH = 4_000;
const RATE_LIMIT = 30;
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT_SCRIPT = `
local count = redis.call("INCR", KEYS[1])
if count == 1 then
  redis.call("PEXPIRE", KEYS[1], ARGV[1])
end
return {count, redis.call("PTTL", KEYS[1])}
`;
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const COMMAND_PROPOSAL_PROMPT = `You are AITerminal, a conversational assistant with a limited local-action proposal feature.
Return exactly one JSON object. For ordinary conversation, use:
{"type":"answer","message":"your response"}
Only when the user explicitly asks you to perform a local action, use:
{"type":"command","message":"brief explanation","action":"one action below","arguments":{}}
Allowed actions and arguments:
- python_version: {}
- install_python: {} (Windows only; installs Python 3.12 using winget)
- create_directory: {"path":"directory path"}
- list_directory: {"path":"directory path"}
- pip_install: {"package":"single package name"}
- create_venv: {"path":"new environment path"}
- run_python_script: {"path":"existing .py file"}
Do not return shell commands, command strings, scripts, or extra argument keys. Never propose deletion, disk formatting, security changes, downloads, or arbitrary shell commands. If a request is ambiguous, unsupported, or asks for a dangerous action, use type "answer" to ask a question or explain the limitation. Never ask for or reveal API keys, passwords, tokens, or other credentials.`;

function response(statusCode, payload, headers = {}) {
  return {
    statusCode,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...headers,
    },
    body: JSON.stringify(payload),
  };
}

function requestIp(event) {
  const platformIp = event.clientContext?.ip;
  if (typeof platformIp === "string" && platformIp.trim()) return platformIp.trim();
  const headers = event.headers || {};
  const platformHeader = Object.entries(headers).find(
    ([name]) => name.toLowerCase() === "x-nf-client-connection-ip",
  )?.[1];
  return typeof platformHeader === "string" && platformHeader.trim() ? platformHeader.trim() : null;
}

function parseBody(event) {
  const raw = event.body ?? "";
  if (typeof raw !== "string") return { error: response(400, { error: "Invalid request body." }) };
  if (Buffer.byteLength(raw, "utf8") > MAX_BODY_BYTES) return { error: response(413, { error: "Request is too large." }) };
  try {
    return { body: JSON.parse(raw) };
  } catch {
    return { error: response(400, { error: "Invalid JSON request." }) };
  }
}

async function checkRateLimit(event) {
  const redisUrl = process.env.UPSTASH_REDIS_REST_URL;
  const redisToken = process.env.UPSTASH_REDIS_REST_TOKEN;
  const ip = requestIp(event);
  if (!redisUrl || !redisToken || !ip || ip.length > 128) {
    return { configured: false };
  }

  let endpoint;
  try {
    endpoint = new URL(redisUrl);
  } catch {
    return { configured: false };
  }
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password) {
    return { configured: false };
  }

  const ipDigest = createHash("sha256").update(ip).digest("hex");
  try {
    const result = await fetch(endpoint, {
      method: "POST",
      headers: {
        authorization: `Bearer ${redisToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify([
        "EVAL",
        RATE_LIMIT_SCRIPT,
        "1",
        `aiterminal:rate:v1:${ipDigest}`,
        String(RATE_WINDOW_MS),
      ]),
      signal: AbortSignal.timeout(3_000),
    });
    if (!result.ok) return { configured: true, available: false };
    const data = await result.json();
    const values = data?.result;
    if (
      !Array.isArray(values) ||
      !Number.isSafeInteger(values[0]) ||
      !Number.isSafeInteger(values[1]) ||
      values[0] < 1 ||
      values[1] < 0
    ) {
      return { configured: true, available: false };
    }
    return {
      configured: true,
      available: true,
      allowed: values[0] <= RATE_LIMIT,
      retryAfter: Math.max(1, Math.ceil(values[1] / 1_000)),
    };
  } catch {
    return { configured: true, available: false };
  }
}

function validateConversation(body) {
  if (typeof body?.message !== "string" || body.message.trim().length === 0 || body.message.length > MAX_QUESTION_LENGTH) {
    return "A message of 1 to 4000 characters is required.";
  }
  const history = body.history === undefined ? [] : body.history;
  if (!Array.isArray(history) || history.length > MAX_HISTORY_MESSAGES) {
    return "Conversation history is invalid or too long.";
  }
  for (const item of history) {
    if (
      !item ||
      !["user", "assistant"].includes(item.role) ||
      typeof item.content !== "string" ||
      item.content.length === 0 ||
      item.content.length > MAX_HISTORY_MESSAGE_LENGTH
    ) {
      return "Conversation history contains an invalid message.";
    }
  }
  return null;
}

function parseAssistantResponse(content) {
  try {
    const parsed = JSON.parse(content);
    if (
      parsed &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      typeof parsed.message === "string" &&
      parsed.message.trim()
    ) {
      if (parsed.type === "answer") return { answer: parsed.message };
      if (
        parsed.type === "command" &&
        typeof parsed.action === "string" &&
        parsed.arguments &&
        typeof parsed.arguments === "object" &&
        !Array.isArray(parsed.arguments)
      ) {
        return {
          answer: parsed.message,
          proposal: { action: parsed.action, arguments: parsed.arguments },
        };
      }
    }
  } catch {
    // Older or incompatible models may still return ordinary plain-text answers.
  }
  return { answer: content };
}

export async function handler(event) {
  if (event.httpMethod !== "POST") return response(405, { error: "Method not allowed." });
  const parsed = parseBody(event);
  if (parsed.error) return parsed.error;

  const rateLimit = await checkRateLimit(event);
  if (!rateLimit.configured) {
    return response(503, { error: "Shared rate limiting is not configured." });
  }
  if (!rateLimit.available) {
    return response(503, { error: "Shared rate limiting is temporarily unavailable." });
  }
  if (!rateLimit.allowed) {
    return response(
      429,
      { error: "Request limit reached. Please try again later." },
      { "retry-after": String(rateLimit.retryAfter) },
    );
  }

  const validationError = validateConversation(parsed.body);
  if (validationError) return response(400, { error: validationError });

  const apiKey = process.env.GROQ_API_KEY;
  const model = process.env.GROQ_MODEL;
  if (!apiKey || !model) return response(503, { error: "AI service is not configured." });

  const requestBody = {
    model,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: COMMAND_PROPOSAL_PROMPT },
      ...(parsed.body.history ?? []).map(({ role, content }) => ({ role, content })),
      { role: "user", content: parsed.body.message },
    ],
  };
  let groqResponse;
  try {
    groqResponse = await fetch(GROQ_URL, {
      method: "POST",
      headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
      body: JSON.stringify(requestBody),
      signal: AbortSignal.timeout(30_000),
    });
    if (groqResponse.status === 400) {
      const compatibleRequestBody = { ...requestBody };
      delete compatibleRequestBody.response_format;
      groqResponse = await fetch(GROQ_URL, {
        method: "POST",
        headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
        body: JSON.stringify(compatibleRequestBody),
        signal: AbortSignal.timeout(30_000),
      });
    }
  } catch (error) {
    if (error?.name === "TimeoutError" || error?.name === "AbortError") {
      return response(504, { error: "The AI service timed out. Please try again." });
    }
    return response(502, { error: "Could not reach the AI service. Please try again." });
  }

  if (!groqResponse.ok) {
    if (groqResponse.status === 401) return response(502, { error: "The AI service credentials are invalid." });
    if (groqResponse.status === 429) return response(429, { error: "The AI service is busy. Please try again shortly." });
    if (groqResponse.status === 400 || groqResponse.status === 404) {
      return response(502, { error: "The configured AI model is unavailable or the request was rejected." });
    }
    return response(502, { error: "The AI service could not complete the request." });
  }

  let data;
  try {
    data = await groqResponse.json();
  } catch {
    return response(502, { error: "The AI service returned an invalid response." });
  }
  const answer = data?.choices?.[0]?.message?.content;
  if (typeof answer !== "string" || answer.trim().length === 0) {
    return response(502, { error: "The AI service returned an invalid response." });
  }
  return response(200, parseAssistantResponse(answer));
}

export const _test = { validateConversation, checkRateLimit };
