# Tests

```bash
uv run pytest tests/ -q
```

These cover the logic where a silent regression would be costly and invisible:

| File | Guards |
|---|---|
| `test_linking.py` | Ticket-key extraction, including the false-positive filter that stops `UTF-8` and `SHA-256` becoming imaginary tickets |
| `test_webhook_security.py` | HMAC verification — the only thing authenticating `/webhooks/github` |
| `test_pr_rendering.py` | That confirmed and unverified findings never render as the same kind of claim, and that detected secrets are reported by location only |
| `test_agent_migration.py` | The LangChain 1.x message contract: tool calls → `ActionResult`, error status handling, and the streaming task lifecycle |

Not covered: live calls to GitHub, Jira, or Slack. Those need real credentials and are
verified by running the agent against a throwaway repo.
