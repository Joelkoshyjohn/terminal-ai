# AITerminal

### Your AI assistant, directly in your terminal.

AITerminal is a cloud-powered AI chatbot that brings conversational AI directly to your command line. Built with Python, Netlify Functions, Groq and Upstash Redis, it provides an interactive terminal experience without requiring users to configure their own AI API keys.

Ask questions, explore ideas, generate code and have contextual conversations — all from your terminal.

---

## Features

- **Interactive CLI:** Simple and clean terminal interface powered by Python and Rich.
- **AI-powered responses:** Uses Groq-hosted language models.
- **Conversational context:** Maintains the last 20 conversation messages during an active session.
- **Cloud-powered architecture:** AI processing happens through a Netlify-hosted backend.
- **No API key required for users:** The Groq API key stays securely on the server.
- **Shared rate limiting:** Upstash Redis protects the public backend from excessive requests.
- **Cross-platform:** Designed for Windows, Linux and macOS.
- **Markdown rendering:** Displays formatted responses and code in the terminal.
- **Lightweight installation:** Users only need Python and internet access.
- **Local actions with approval:** Reviews allowlisted command proposals and requires fresh confirmation before each local action.

## Architecture

AITerminal uses a client-server architecture.

```text
                USER
                  |
                  v
          Python CLI Application
                  |
                  | HTTPS Request
                  v
           Netlify Functions
                  |
           +------+------+
           |             |
           v             v
      Upstash Redis    Groq API
      Rate Limiting   AI Processing
           |             |
           |             v
           |        AI Response
           |             |
           +------+------+
                  |
                  v
           Netlify Backend
                  |
            Answer or structured
            local-action proposal
                  |
                  v
           Python CLI validates
           and asks permission
                   |
                   v
           Local computer
```

### Technology Stack

| Component | Technology | Responsibility |
|---|---|---|
| CLI | Python | User interaction |
| Terminal UI | Rich | Terminal formatting |
| CLI framework | Typer | Command-line interface |
| Backend | Netlify Functions | API processing |
| AI provider | Groq API | AI response generation |
| Rate limiting | Upstash Redis | Shared request counters |
| Distribution | PyPI | Python package distribution |
| Version control | Git and GitHub | Source code management |

## How It Works

1. The user enters a question in the terminal.
2. The Python CLI sends the question and recent conversation history to the Netlify backend.
3. The backend validates the request.
4. Upstash Redis checks the request rate limit.
5. If permitted, the backend forwards the question to Groq.
6. Groq generates an AI response.
7. Netlify returns an answer or a structured local-action proposal; it never executes local commands.
8. The CLI displays and validates a proposal, asks for approval, and executes an approved action locally.
9. The CLI displays the local result. It asks separately before sending captured output to the AI for an explanation.

## Conversational Context

AITerminal supports short-term conversational context.

During an active session, the CLI maintains a conversation history containing user messages and AI responses.

- Maximum retained context: 20 messages.
- History is maintained in Python process memory.
- The `clear` command clears the current conversation.
- The `exit` command ends the session and discards its history.

**Note:** Persistent memory across terminal sessions and permanent conversation storage are not currently implemented.

## Rate Limiting

AITerminal uses Upstash Redis to enforce shared backend rate limiting.

Current implementation:

| Setting | Value |
|---|---|
| Request limit | 30 requests |
| Time window | 60 seconds |
| Limiting method | Client IP |
| Redis key | SHA-256 hashed IP |
| Counter expiration | 60 seconds |
| Storage | Temporary request counters |

The backend uses an atomic Redis operation to maintain consistent counters across serverless function instances.

If Redis is unavailable or incorrectly configured, the backend fails closed with HTTP 503.

This protects the service from excessive requests but does not provide individual user authentication or separate quotas for each user.

Groq's own account and model rate limits also apply.

## Installation

### Requirements

- Python 3.10 or newer
- Internet connection
- Windows, Linux or macOS

Users do not need:
- A Groq API key
- A Netlify account
- Node.js
- Redis installation
- Git

### Install from PyPI

The package name is `termchat-ai`, and its terminal command is `aiterminal`.

After the package is published to official PyPI:

```bash
python -m pip install termchat-ai
```

Start the application:

```bash
aiterminal
```

### Windows

```powershell
py -m pip install termchat-ai
aiterminal
```

### Linux

```bash
python3 -m pip install termchat-ai
aiterminal
```

On Linux distributions that manage system Python packages, use a virtual environment:

```bash
python3 -m venv ~/aiterminal-env
source ~/aiterminal-env/bin/activate
python -m pip install termchat-ai
aiterminal
```

### macOS

```bash
python3 -m pip install termchat-ai
aiterminal
```

## Usage

After launching AITerminal:

```text
Connecting to AITerminal Cloud...
AITerminal ready!

You> What is artificial intelligence?

AI>
Artificial intelligence is a field of computer science
that focuses on creating systems capable of performing
tasks that normally require human intelligence.

You> Explain machine learning.

AI>
Machine learning is a subset of artificial intelligence...

You> clear

You> exit

Goodbye!
```

### Available Commands

| Command | Description |
|---|---|
| `clear` | Clear the terminal and conversation history |
| `/clear` | Alternative clear command |
| `exit` | Exit AITerminal |
| `quit` | Alternative exit command |

### Local actions

When asked to perform a supported task, AITerminal displays the proposed operation and asks `Run this local action? [y/N]`. Each action requires a new approval; declining it cancels that action. Supported operations are:

- Check the current Python interpreter version.
- Install Python 3.12 on Windows through the fixed `winget` package ID `Python.Python.3.12`.
- Create a new directory or list entries in a directory.
- Install one named Python package from the configured package index, using binary distributions only.
- Create a new Python virtual environment at a path that does not already exist.
- Run an existing `.py` file with the current Python interpreter.

The executor does not accept shell strings, and it does not support deleting files, disk formatting, security-setting changes, or downloading and executing scripts. Running a Python file executes that file's code; installing a package may also execute package code. Review the displayed operation and the file/package before approving.

Every process has a timeout (120 seconds, or 300 seconds for installs), and stdout and stderr are capped at 16 KiB each. To ask the AI to explain a result, AITerminal asks separately and defaults to no. Only after approval does it send the captured output and exit status to the cloud. Common credential patterns are masked and sensitive environment variables are not passed to launched processes, but output can still contain private information: inspect it and decline sharing when in doubt. Local output is not added to conversation history.

## Backend Deployment

AITerminal's backend runs on Netlify Functions.

Configured production endpoint:

`https://aiterminal-cloud.netlify.app`

### Environment Variables

Configure the following variables in Netlify:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Secret Groq API key |
| `GROQ_MODEL` | Selected Groq model |
| `UPSTASH_REDIS_REST_URL` | Upstash Redis REST endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | Secret Upstash Redis token |

Never include these credentials in the Python package, GitHub repository or public documentation.

### Backend Deployment Steps

1. Push the project to GitHub.
2. Connect the repository to Netlify.
3. Configure the build and function settings from `netlify.toml`.
4. Configure the required environment variables.
5. Deploy the application.
6. Test the health and chat endpoints.

### Health Check

PowerShell:

```powershell
$site = "https://aiterminal-cloud.netlify.app"

Invoke-RestMethod "$site/.netlify/functions/health"
```

Expected response:

```json
{
  "status": "ok"
}
```

## Project Structure

```text
AITerminal/
│
├── cli/
│   ├── src/
│   │   └── aiterminal/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       ├── terminal.py
│   │       ├── client.py
│   │       └── executor.py
│   │
│   ├── tests/
│   └── pyproject.toml
│
├── netlify/
│   └── functions/
│       ├── chat.mjs
│       └── health.mjs
│
├── docs/
│
├── public/
│
├── netlify.toml
├── package.json
├── package-lock.json
├── .gitignore
└── README.md
```

## Development Setup

### Clone the repository

```bash
git clone https://github.com/Joelkoshyjohn/terminal-ai.git
cd terminal-ai
```

### Set up the Python CLI

Windows:

```powershell
cd cli

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install -e .
```

Linux/macOS:

```bash
cd cli

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -e .
```

### Set up the backend

From the project root:

```bash
npm install
```

Configure the required local environment variables without committing secrets.

## Testing

### Backend Tests

```bash
npm test
```

Backend tests use stubs for Redis and Groq so that tests do not require real API credentials.

### Python CLI Tests

```bash
python -m pip install pytest
python -m pytest -c cli/pyproject.toml cli/tests
```

### Build Python Distribution

From the CLI directory:

```bash
python -m pip install hatchling
python -m hatchling build
```

## Security and Privacy

AITerminal is designed to keep provider credentials on the server.

- Groq API credentials are stored in Netlify environment variables.
- Upstash credentials are stored in Netlify environment variables.
- The Python CLI communicates with the backend over HTTPS.
- Redis stores temporary hashed-IP rate-limit counters.
- Conversation messages are not permanently stored by the backend.
- Conversation history is maintained temporarily in the CLI process.
- Local command output is never sent to the cloud unless the user approves that separate disclosure.

**Important:** The chat endpoint is publicly accessible and does not currently implement user authentication. Avoid submitting sensitive personal information.

## Development Workflow

AITerminal uses Git for source-code management.

Recommended workflow:

1. Keep `main` as the stable branch.
2. Create feature branches for new development.
3. Implement and test changes independently.
4. Push feature branches to GitHub.
5. Create Pull Requests.
6. Review and test changes before merging into `main`.

Example:

```bash
git switch -c feature/ai-memory

git add .
git commit -m "Add AI memory feature"

git push -u origin feature/ai-memory
```

## Roadmap

Planned improvements for future versions:

- [ ] Persistent conversational memory
- [ ] Conversation history management
- [ ] Multiple AI provider support
- [ ] AI model selection
- [ ] Streaming responses
- [ ] Document and PDF interaction
- [ ] Voice interaction
- [ ] User accounts and authentication
- [ ] Usage and token monitoring dashboard
- [ ] Browser-based interface

These are planned features and are not represented as currently implemented functionality.

## Contributing

Contributions, suggestions and bug reports are welcome.

To contribute:

1. Fork the repository.
2. Create a feature branch.
3. Implement your changes.
4. Add or update tests.
5. Submit a Pull Request.

Please do not include API keys, tokens or other credentials in contributions.

## License

A license has not yet been specified. Add an appropriate open-source license before presenting the repository as an open-source project.

---

**AITerminal**

*Bringing conversational AI to your command line.*

GitHub: https://github.com/Joelkoshyjohn/terminal-ai

Cloud Backend: https://aiterminal-cloud.netlify.app
![complete working](worikng.jpeg)