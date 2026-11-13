# Repository guidance

See AGENTS.md for the project's architecture, commands, and contribution rules.

## Hub discovery

When HARMONY_IP is unset or empty, app.py discovers a Hub using SSDP on the first
connection request. Discovery is bounded, ignores unrelated responses, deduplicates
Hub addresses, and requires an explicit IP if multiple Hubs respond. It uses the
response sender's IPv4 address and never fetches advertised URLs. Client creation
is serialized; only connected clients are cached, allowing discovery to retry
after failure. Explicit HARMONY_IP values bypass discovery.

Test discovery using mocked sockets and connection setup using mocked HarmonyAPI
clients; tests must not send commands to real devices. See README.md for network
requirements and container setup limitations. Keep dependency versions in the
requirements files.

The async bridge serializes background-loop startup across Flask request threads.
Readiness is signaled from inside the running loop. Preserve the concurrent
startup regression test when changing this bridge.

The frontend schedules activity-list refreshes after each request completes:
retry failures every five seconds and refresh successful responses every minute.
Only changed lists redraw cards. Run `node tests/test_frontend.js` to verify retry,
recovery, and unchanged-list behavior without contacting the Hub.

The Next transport button is capability-gated from the command list of the
activity's selected transport device. It supports Harmony's `Next` and
`NextTrack` command names. Preserve PassThroughActivityRole precedence over
PlayMediaActivityRole so Squeezebox commands do not go to the CD player.
