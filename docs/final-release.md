# Final source release — September 13, 2026

The local Hermes buyer, voice demo, egress helpers, and dedicated Docker networks
were shut down. Automatic intake and procurement were disabled. No hackathon
autostart jobs were found. Remote supplier shutdown was requested from its owners;
this is not confirmation of their cloud service's state.

The final source tree excludes runtime credentials, account configuration, raw
conversations, recordings, model traces, private run state, and temporary audit
files. Live account and communication references in documentation are replaced
with placeholders; recorded commercial figures and stated limitations are retained.
Public contributor credits and fictional business fixtures remain.

Identity-sensitive runtime configuration must be provided locally. Do not reuse
placeholder IDs or addresses as a live setup. Existing recorded evidence examples
have redacted identifiers and are not fresh quotes or purchase authorizations.
Historical supplier hostnames are removed from defaults; a new supplier hostname
must be explicitly reviewed and added to the egress allowlist.

Before the final push, the review used Gitleaks against fetched Git history,
direct matching of configured API key values and common encodings against every
reachable Git object, and a separate manual privacy review. No actual credential
leak was found. The final staged source is scanned again before publication.

The source cleanup and a rewrite of historical commits are separate operations.
Earlier commits may retain previously published conversations and contributor
email metadata unless a history rewrite is separately approved.

Offline validation passed: 369 Python tests (plus 217 subtests) and 20 Node tests.
The final voice changes isolate recordings by call, stop microphone capture on
hangup, validate uploads, and save private evidence with owner-only permissions.
No paid API calls or hackathon services were started for this verification.

The project owner authorized deletion of the entire local hackathon folder only
after verifying the final source commit on GitHub. Private recordings and runtime
configuration are intentionally excluded from that push and are deleted locally
with the folder.
