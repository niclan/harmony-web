# AGENTS.md

Guidance for LLMs changing this repository.

## Documentation Ownership

- Read [README.md](README.md) for the app's purpose, features, setup,
  test commands, configuration, API, and deployment/security
  assumptions.
- See [deployment/README.md](deployment/README.md) for detailed
  deployment instructions and [requirements.txt](requirements.txt) /
  [requirements-dev.txt](requirements-dev.txt) for dependencies.
- Keep user-facing instructions in README.md and coding rules
  here. Link to existing documentation instead of repeating commands,
  configuration defaults, endpoint lists, dependency versions, or test
  counts.
- Keep documentation, code and setup aligned.

## Separation of Concerns

- Keep Hub communication and validation in `harmony.py`. This module
  must work without Flask or an HTTP request context.
- Keeb Web app and web rendering support in `app.py`. Routes call the
  public Harmony functions; they must not access the Hub client,
  configuration, or event loop directly.
- Put new behavior in the layer that owns it.
- If a new logical context is introduced ask operator about
  abstracting it.

## Hub Implementation Rules

- Keep one persistent client and background event loop per
  process. Synchronize loop startup and client creation so concurrent
  callers do not create competing connections. Importing the module
  must not connect to the Hub.
- Run coroutines on that loop with
  `asyncio.run_coroutine_threadsafe()`. Do not create a fresh loop for
  each web request.
- Copy activity dictionaries before the web layer adds image URLs; do
  not mutate the client's configuration for presentation.
- Treat `client.current_activity` as an `(activity_id, activity_name)`
  tuple. Activity ID `"-1"` means powered off; reject volume and
  transport commands in that state.
- Resolve volume commands using the activity's `VolumeActivityRole`.
- Resolve transport commands from `roles['PassThroughActivityRole']`
  first, then `roles['PlayMediaActivityRole']`. If neither exists,
  transport controls are unavailable.
- Do not use activity `controlGroup` mappings to select devices: those
  mappings may be misconfigured. Inspect the selected device's
  advertised commands only to determine command support, such as
  `Next` versus `NextTrack`.
- Validate activity IDs against Hub configuration before starting an
  activity. Send commands with `SendCommandDevice`, using the selected
  device ID and the proper command name.

## Web and Browser Rules

- Register application routes through the existing Blueprint so URL
  prefix support is preserved. Keep generated links and API calls
  compatible with prefixed deployments.
- Keep the browser UI dependency-free unless a concrete requirement
  justifies a dependency.
- Preserve the black background, white cards, active activity border,
  and always-visible controls. Disable unavailable controls rather
  than hiding them.
- Avoid unnecessary DOM replacement during polling. Preserve the
  activity-transition grace period so refreshes do not overwrite user
  actions.
- Volume controls must accept rapid repeated presses; do not block
  clicks while a request is pending.
- Keep cached activity images under `static/images/activities/`; do
  not commit downloaded images. Preserve fallback icons when downloads
  fail and reuse valid cached images.

## Security Rules

- Validate input types before processing, then validate formats or
  allowed values. Check identifiers and capabilities at the Hub
  boundary as well as validating HTTP inputs.
- Preserve the image-download protections in `app.py`: validate the
  complete HTTPS URL against the CDN allowlist, reject redirects,
  enforce the size limit while streaming, validate image signatures,
  and restrict cache filenames.
- Use unique temporary files for downloads, publish only validated
  files, close responses, and clean up temporary files on failure.
- Return generic messages for unexpected failures and log full
  tracebacks internally. Expose validation messages only when they are
  safe for users.
- Preserve production logging and debug-mode restrictions described in
  README.md.
- Never execute shell commands
- Render hub-provided text with DOM `textContent` and attach event
  listeners; never interpolate it into HTML attributes or inline
  JavaScript.

## Verification and Maintenance

- Use the test commands in
  [README.md](README.md#running-tests). Update regression tests when
  changing behavior; mock Hub communication so tests do not require
  physical devices.
- Test Hub behavior in `tests/test_harmony.py` with a mocked
  client. Test HTTP behavior in `tests/test_app.py` by mocking the
  public Harmony interface; use client-level mocks only for deliberate
  integration tests.
- Cover browser behavior in `tests/test_frontend.js`, including
  polling recovery and repeated volume presses when those paths
  change.
- Keep error responses and status codes compatible unless a requested
  change requires otherwise.
