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
| GitHub Copilot | Official Copilot SDK | Authorized GitHub token | Planned; selection fails explicitly |

Endpoints are explicit. Base-URL environment variables cannot redirect keys to
another host, HTTP redirects are disabled, and the HTTP client does not inherit
environment proxies. Automatic SDK retries are disabled. An error never triggers
a request to a second provider.

## Results and limits

- `success` means a complete text response without an internal error. It does not
  change a task's state or establish that its acceptance criteria are met.
- HTTP 401/403 become `auth_error`, 429 becomes `rate_limited`, and 408/5xx or
  connection failures become `transient_error`. A timeout becomes `timeout`.
- Malformed responses, refusals, incomplete messages or reasoning, and unhandled
  tool calls become `invalid_output`. Exception strings, response headers, and
  error bodies are never returned as diagnostics.
- Missing token or cost observations stay unknown. Token counts do not establish
  remaining quota or an exact cost. The HTTP timeout is not a global scheduling
  watchdog or a guaranteed financial budget.
- Shared result fields are `status`, `response_id`, `text`, `error_code`,
  `duration_seconds`, and optional `usage`. The retired CLI-only exit-code and
  stream fields are no longer part of this pre-release result model.

Tests intercept SDK HTTP transports with fictional credentials. Real account
qualification remains open; no automated test incurs API charges.

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

## Official references checked on November 2, 2026

- [Claude Messages](https://platform.claude.com/docs/en/api/messages): models,
  user messages, output limits, response content, and observed usage.
- [Claude models](https://platform.claude.com/docs/en/models/overview): example
  identifiers; documentation does not establish account access.
- [OpenAI Responses](https://developers.openai.com/api/reference/python/resources/responses/methods/create):
  input, output-token limits, generation status, and text output. The adapter
  explicitly requests `store=False`.
- [Copilot SDK authentication](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/authenticate):
  GitHub authentication and tokens specific to Copilot. A future adapter will use
  the official SDK without private endpoints or implicit `gh auth` credentials.

The abandoned subscription CLI implementation is available only in Git history;
see checkpoint CP-015 in [checkpoint.md](checkpoint.md) when investigating it.
