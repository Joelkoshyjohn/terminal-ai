# AITerminal

AITerminal is a terminal chatbot: a Python CLI sends questions over HTTPS to public Netlify Functions, which call Groq using a server-side API key.

```text
Python CLI --HTTPS--> Netlify Functions --GROQ_API_KEY--> Groq
                            |
                            +--> Upstash Redis (shared rate-limit counters only)
```

There is no login, password, token, web frontend, or permanent chat storage. Conversation context stays in the CLI process and is sent with each question. The backend does not persist messages.

## Status and requirements

The source is configured to use `https://aiterminal-cloud.netlify.app` by default. The live health and chat endpoints both responded successfully during this release preparation; recheck them before publishing. The package has **not** been published to PyPI.

End users need Python 3.10+ and internet access, but no Groq API key, account, Node.js, Git, or SSH. The service owner needs Netlify, Groq, and Upstash Redis accounts. The backend is public and has no user identity; shared per-IP rate limits and provider usage limits are therefore important.

## Deploy the backend to Netlify

1. Create a GitHub repository and upload this project, including `netlify/functions`, `netlify.toml`, `package.json`, and `package-lock.json`. Do not add a `.env` file or secrets.
2. In Netlify, select **Add new site** → **Import an existing project**, connect the repository, and authorize access.
3. Use the settings in `netlify.toml`: no build command, `public` as the publish directory, `netlify/functions` as the functions directory, and Node.js 20.
4. Create an Upstash Redis database and enable its HTTPS REST API. From the database console, copy the REST URL and REST token. Use a database in a region close to the Netlify site when practical.
5. In Netlify **Site configuration** → **Environment variables**, configure these server-side values for the deployed context:

   | Variable | Value |
   | --- | --- |
   | `GROQ_API_KEY` | Groq API key |
   | `GROQ_MODEL` | A currently available Groq chat-completion model |
   | `UPSTASH_REDIS_REST_URL` | Upstash database REST URL |
   | `UPSTASH_REDIS_REST_TOKEN` | Upstash database REST token |

   These settings belong only in Netlify. Never commit them, put them in the Python package, or paste them in logs. The CLI only receives the answer. Re-deploy after changing variables.
6. Enable HTTPS for the Netlify site in its dashboard. Copy the actual site URL shown there; do not use a guessed URL.
7. After configuring the URL, test the deployment as described below.

### Shared rate limiting

Netlify Functions can run on separate and short-lived instances, so a process-local counter is not a reliable global limit. The chat function instead uses Upstash Redis and a single atomic Lua increment with a 60-second expiration. It allows up to 30 requests per platform-provided client IP per fixed one-minute window. IPs are SHA-256 hashed for Redis keys; request messages are never stored in Redis. If the Upstash configuration is missing, invalid, or unavailable, the function fails closed with HTTP 503 rather than sending a request to Groq.

Upstash Redis is an additional server-side service required for the implemented shared rate limit. Configure its REST URL and token as Netlify environment variables. This is IP-based control, not account authentication: clients may share an IP or change IPs. Apply provider spending limits/alerts and consider an additional edge firewall or API gateway if the public endpoint needs stronger abuse controls. Redis request counters expire after one minute; conversation content is not persisted.

### Test a deployed site

The configured site URL is `https://aiterminal-cloud.netlify.app`. Confirm it matches the URL shown in the Netlify dashboard.

PowerShell:

```powershell
$site = "https://aiterminal-cloud.netlify.app"
Invoke-RestMethod "$site/.netlify/functions/health"
```

The health endpoint is a public liveness check and returns `{"status":"ok"}`. To test chat without an API key, send a JSON request to the chat endpoint:

```powershell
$body = @{ message = "What is Python?"; history = @() } | ConvertTo-Json
Invoke-RestMethod "$site/.netlify/functions/chat" -Method Post -ContentType "application/json" -Body $body
```

A successful response contains an `answer` string. Requests missing or unable to reach shared rate limiting return HTTP 503. Requests over the per-IP limit return HTTP 429. Groq keys and Upstash tokens are never returned by these endpoints.

## Install and use the CLI

The package name is `termchat-ai`; its executable command remains `aiterminal`. The package is not published yet.

Install from PyPI after publication:

```powershell
py -m pip install termchat-ai
aiterminal
```

```sh
python -m pip install termchat-ai
aiterminal
```

For development from a local checkout, Windows PowerShell:

```powershell
py -m pip install .\cli
aiterminal
```

Linux and macOS:

```sh
python3 -m pip install ./cli
aiterminal
```

No login, password, token, or API key is requested. The client defaults to the HTTPS URL `https://aiterminal-cloud.netlify.app`; `AIT_TERMINAL_API_URL` may override it. HTTP is accepted only for localhost development.

Example:

```text
Connecting to AITerminal Cloud...
AITerminal ready!
You> What is Python?
AI>
Python is a high-level programming language used for many kinds of software.
You> clear
You> exit
Goodbye!
```

Use `clear` or `/clear` to clear the screen and forget the current session's conversation context. Use `exit` or `quit` to end the session. Rich formats readable Markdown and code in the terminal. The last 20 context messages are held only in process memory and discarded when the CLI exits.

## Development and tests

Backend tests stub both Redis and Groq; no real service credentials or requests are needed:

```sh
npm test
```

CLI tests:

```sh
python -m pip install -e "./cli"
python -m pip install pytest
python -m pytest -c cli/pyproject.toml cli/tests
```

Build the Python wheel and source distribution from the CLI package directory:

```sh
cd cli
python -m hatchling build
```

The Netlify Functions use Node.js built-ins and the Python package dependencies are declared in `cli/pyproject.toml`.

## Security and data handling

- The unauthenticated chat endpoint is public. Do not send sensitive information that should not be sent to Groq.
- `GROQ_API_KEY` remains a Netlify server-side environment variable. The client contains only the public backend URL.
- Request bodies are limited to 64 KiB; the current question and each history message are limited to 4,000 characters; at most 20 prior messages are accepted. Responses disable caching.
- Groq calls have a 30-second timeout; the CLI network timeout is 35 seconds. Safe errors are returned without upstream credentials or detailed upstream bodies.
- Conversation history is only in CLI process memory and is cleared on exit. Netlify Functions do not write messages to storage or logs. Redis stores only short-lived, hashed-IP rate counters.
- Shared Redis rate limiting fails closed, but it does not prevent abuse via rotating IP addresses. Set usage alerts and provider spending limits.

## PyPI release checklist

The CLI is configured with package name `termchat-ai` and command `aiterminal`, but it has not been published.

1. Verify the default URL matches the deployed site and test health and chat over HTTPS.
2. Replace project author and repository metadata in `cli/pyproject.toml` with real project information.
3. Check `https://pypi.org/pypi/termchat-ai/json` immediately before publishing; package-name availability can change.
4. Run both test suites, rebuild and inspect the wheel and source distribution, and publish using the maintainer's PyPI credentials. Never commit a PyPI token.

Do not consider deployment or publication complete until it has been independently verified.
