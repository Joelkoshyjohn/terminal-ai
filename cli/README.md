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
