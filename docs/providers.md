# Provider contract — token_maxxxer

`Provider.generate(GenerationRequest, SecretStr)` returns a `GenerationResult`.
Request settings include the selected provider, explicit model, output-token
limit, and HTTP timeout. `query` generates text. `night` builds its typed JSON
file-tool protocol on this same text interface; the SDK's native tool-call blocks
remain unsupported by the text adapter. Night sessions have a separate global
deadline, call-count limit and approved verification commands.

## Implementations

| Provider | Transport | Credential | Status |
| --- | --- | --- | --- |
| Claude | Official Anthropic SDK, Messages API | `ANTHROPIC_API_KEY` or private reference | Implemented; simulated HTTP tests |
| OpenAI | Official OpenAI SDK, Responses API | `OPENAI_API_KEY` or private reference | Implemented; simulated HTTP tests |
| Codex | Official `codex exec --json` CLI | Existing CLI login, including ChatGPT sign-in | Implemented; ephemeral text generation |
| GitHub Copilot | Optional official Copilot SDK | Explicit token/reference or SDK logged-in-user discovery | Implemented; simulated SDK tests |

Endpoints are explicit. Base-URL environment variables cannot redirect keys to
another host, HTTP redirects are disabled, and the HTTP client does not inherit
environment proxies. API SDK retries are disabled. Another provider is used only
when it is explicitly configured as an authorized fallback.

## Authorized fallback

```yaml
provider:
  name: claude
  model: claude-sonnet-5-5
  fallback_on: [quota_exhausted]
  fallbacks:
    - name: codex
      model: gpt-6.1-sol
    - name: copilot
      model: gpt-6-astra
```

Each provider/model must be authorized explicitly. Model IDs are examples;
verify access in each account. See [the complete example](../examples/provider-fallbacks.yaml).
Night commands also accept repeated `--fallback PROVIDER:MODEL` flags.
Previews show the order without resolving credentials or launching runtimes.

An exhausted provider advances to the next configured entry. The same pending
prompt, action history, worktree, read versions, checks and publication state
remain available. No action from a failed response executes. Selection stays on
the new provider instead of retrying the exhausted account for every action.
Chains are flat, contain at most three alternatives, cannot repeat a provider/model
pair, and stop after the final provider is exhausted.

Only `quota_exhausted` triggers fallback by default. Add `rate_limited` to
`fallback_on` to authorize switching on temporary throttling. Authentication
errors, malformed responses, network failures, timeouts and failed verification
do not switch providers. Missing fallback credentials fail explicitly.

Every attempt, including a quota rejection, consumes one night call slot and is
journaled before generation. The session deadline continues through switches;
`query` shares one timeout across its chain. Runtime-internal network requests
are not separate application call slots. Each account has its own allocation;
fallback is not unlimited or free.

## Local runtimes

Codex requires an installed CLI and an existing `codex login` session. Check it
with `codex login status`. The application does not extract OAuth tokens or
read `auth.json`. API-key environment overrides are not inherited by the child.
Codex starts in an empty temporary directory with ephemeral sessions, a read-only
sandbox, user configuration disabled, and shell, apps, plugins, web search and
agent capabilities disabled. Unexpected tool events are rejected.

Install Copilot support with `uv sync --locked --extra copilot`. An explicit
Copilot token/reference disables logged-in-user fallback. Otherwise the official
SDK owns its documented login discovery, which can use CLI/IDE or GitHub CLI
authentication; the application does not call `gh auth token` itself. The SDK
exposes no tools and disables configuration discovery, skills, hooks, session
storage and host Git operations. It explicitly declines permission requests.
It runs in an owned subprocess; timeouts and
cancellation terminate the process group.

Both runtimes generate text actions for the existing supervisor. They do not
receive the selected repository as their working directory. Prompts and explicit
Copilot credentials travel through anonymous stdin files, never argv, environment
variables or persisted session journals. `max_output_tokens` remains an API
setting; native runtimes control their own output-token limits. Capture bounds,
timeouts and application call limits still apply.

## Results and limits

- `success` means a complete text response without an internal error. It does not
  change a task's state or establish that its acceptance criteria are met.
- Recognized empty-credit/billing errors, including Anthropic HTTP 400 and
  OpenAI `insufficient_quota`, become `quota_exhausted`.
- HTTP 401/403 become `auth_error`, ordinary 429 becomes `rate_limited`, and 408/5xx or
  connection failures become `transient_error`. A timeout becomes `timeout`.
- Malformed responses, refusals, incomplete messages or reasoning, and unhandled
  tool calls become `invalid_output`. Exception strings, response headers, and
  error bodies are never returned as diagnostics.
- Missing token or cost observations stay unknown. Token counts do not establish
  remaining quota or an exact cost. The HTTP timeout is not a global scheduling
  watchdog or a guaranteed financial budget.
- Shared result fields are `status`, `response_id`, `text`, `error_code`,
  `duration_seconds`, optional `usage`, and provider/model attribution when routed.
  Night events record provider transitions. The retired CLI-only exit-code and
  stream fields are no longer part of this pre-release result model.

Automated tests intercept HTTP, SDK clients and temporary executables with
fictional credentials; they never call real model services. Operational evidence
is recorded separately in [checkpoint.md](checkpoint.md).

## Credentials

Resolve the selected provider's process key first, then its
`TOKEN_MAXXXER_<PROVIDER>_CREDENTIAL_REF` environment value or private `.env`
reference. The reader does not mutate `os.environ` or interpolate values, and
rejects plaintext API keys in `.env`.

macOS references use `keychain://service/account`. An explicit `query` or confirmed
`night` session retrieves the selected value through the system tool, with a
timeout and no secret output. Night previews never retrieve it.
`doctor` only checks configuration. Linux currently supports process environment
keys. A reference is not a secret and never creates a Keychain entry itself.

## Official references checked on November 7, 2026

- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Codex authentication](https://developers.openai.com/codex/auth)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Copilot SDK Python reference](https://github.com/github/copilot-sdk/blob/main/python/README.md)

- [Claude Messages](https://platform.claude.com/docs/en/api/messages): models,
  user messages, output limits, response content, and observed usage.
- [Claude models](https://platform.claude.com/docs/en/models/overview): example
  identifiers; documentation does not establish account access.
- [OpenAI Responses](https://developers.openai.com/api/reference/python/resources/responses/methods/create):
  input, output-token limits, generation status, and text output. The adapter
  explicitly requests `store=False`.
- [Copilot SDK authentication](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/authenticate):
  GitHub authentication, explicit tokens and the SDK's logged-in-user discovery.

The abandoned subscription CLI implementation is available only in Git history;
see checkpoint CP-015 in [checkpoint.md](checkpoint.md) when investigating it.
