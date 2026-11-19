# AITerminal CLI

This package provides the `aiterminal` terminal command. It connects directly to the public AITerminal chat function; it does not ask users to log in and does not contain a Groq API key.

## Install

The package is named `termchat-ai` and is not published yet. After publication:

```powershell
py -m pip install termchat-ai
aiterminal
```

Linux and macOS:

```sh
python -m pip install termchat-ai
aiterminal
```

For development from a checkout:

```sh
python -m pip install ./cli
aiterminal
```

The client uses `https://aiterminal-cloud.netlify.app` by default. Override with `AIT_TERMINAL_API_URL` if needed.

Use `clear` or `/clear` to clear the screen and temporary conversation context; use `exit` or `quit` to end the session. Context is memory-only and is discarded when the process exits.

## Local actions

For supported requests, AITerminal shows a structured local-action proposal and asks for explicit approval each time. The cloud service only proposes actions; execution happens on your computer.

Supported actions:

- Check the current Python version.
- Install Python 3.12 on Windows with the fixed `winget` package ID `Python.Python.3.12`.
- Create a directory or list a directory's entries.
- Install a single named Python package from the configured package index (binary distributions only).
- Create a new virtual environment in a path that does not already exist.
- Run an existing Python script.

The executor uses validated arguments and `subprocess` with `shell=False`. It does not accept arbitrary shell text and does not provide delete, disk-format, security-setting, or download-and-execute operations. Running a Python script executes its code, and installing packages can execute package code; review each proposal before approving it.

Each process is limited to 120 seconds (300 seconds for installs), with stdout and stderr capped at 16 KiB each. Command output stays local unless you separately approve sending it to the cloud for an AI explanation. Common credential patterns are masked and sensitive environment variables are excluded from child processes; still review output before sharing it.
