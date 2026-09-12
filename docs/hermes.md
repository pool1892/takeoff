# Repo-local Hermes

Run all Hermes commands from the repository with `scripts/hermes`. The launcher
refuses to fall back to running an agent on the host.

```bash
scripts/hermes init
scripts/hermes pull
scripts/hermes credentials
scripts/hermes smoke
scripts/hermes network-smoke
scripts/hermes --version
scripts/hermes chat
scripts/hermes bridge-start
scripts/hermes bridge-status
scripts/hermes bridge-stop
```

`pull` downloads the official image and records its immutable digest in
`runtime/hermes/image.txt`. Subsequent launches use that digest. Docker maintains
its normal shared image cache on the host; all Takeoff credentials, configuration,
memory, session history, CLI packages, and generated files stay inside this repo.
There is no global Hermes installation, shell-profile edit, or startup service.

If Docker needs sudo, run these commands in the visible **Admin — Takeoff Docker**
Herdr pane (or your SSH terminal). Enter the password there. Authentication in one
terminal does not authenticate another agent runner. The launcher supports either
your normal shell with sudo for Docker, or the authorized admin shell. In both
cases the agent container runs as the non-root repository owner.

`credentials` uses hidden terminal input for the new OpenAI key and the new
`takeoffAI` buyer agent token. Blank input preserves an existing value. Never pass
keys as command arguments or commit them. Runtime configuration is in
`.local/hermes/config.yaml` and credentials are in `.local/hermes/.env`, both
ignored by Git. Initialization preserves existing files.

The configured experimental buyer model is `gpt-5.6-sol` with medium reasoning
(`medium`) and Fast processing through
a named direct OpenAI Responses provider. Change `model.default` in the local
config and the two bridge invocation arguments together to select another model
your key can access. Explicit model arguments prevent a resumed session from
restoring its earlier model. The template uses `compression.tail_mode: legacy`
so the configured 0.20 tail ratio takes effect.
The provider points explicitly at `https://api.openai.com/v1`; it does not reuse
personal Hermes credentials or an OpenRouter account.

`bridge-start` keeps the isolated container and its restricted network running
after the command returns. `bridge-stop` removes both containers and that network;
it preserves local conversation state. No system startup service is installed.
The chat bridge connects contractor direct messages in Ambiguous to actual Hermes
turns. It also processes explicitly configured assigned procurement tasks through
the [procurement listener and tools](procurement.md); that path retains one native
Hermes session per task and resumes it on supplier replies or contractor comments.

## Browser voice server

Start the human-supplier browser call server in the same isolated runtime:

```bash
scripts/hermes voice-web --request /workspace/.local/hermes/voice/request.json
```

The request file must already exist at `.local/hermes/voice/request.json` on the
server; its contents define the authorized call. The module's example is used if
`--request` is omitted. This foreground command runs
`python -m integrations.voice.human_call`, prints the seller page URL with its
session-access token, and keeps running until Ctrl-C. Keep that URL private.
The OpenAI key is loaded only from the existing repo-local runtime `.env`, and
call evidence is saved under `.local/hermes/voice/calls`. No host key fallback is
introduced. Stop the server with Ctrl-C to remove its containers and network;
the separate chat listener and saved evidence remain available.

Only **127.0.0.1:3000** on this server is published. The buyer stays on its
gateway-free internal network. Its credential-free egress helper also relays
this one port to the buyer's voice server; the reviewed HTTPS allowlist remains
in force. No public host address or arbitrary port can be selected with this
launcher. The voice module listens on `0.0.0.0:3000` inside its container so that
the helper can reach it; this does not publish that address on the host.

For a browser on the hackathon Mac while this server is at home, use Tailscale
for host reachability and an SSH local tunnel. Replace `TAILSCALE_HOST` with the
home machine's actual Tailscale hostname or address, then run on the Mac:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:3000:127.0.0.1:3000 cs@TAILSCALE_HOST
```

Open the printed `http://127.0.0.1:3000/s/.../` URL in the Mac's browser and allow
microphone access. The localhost URL supports the browser's secure-context
microphone requirement without exposing the server publicly. The browser also
needs access to OpenAI for WebRTC audio. If port 3000 is busy on the Mac, stop the
conflicting local listener before opening the tunnel. Launcher tests verify
command construction and cleanup; a live page load and voice session must still
be verified after startup. See [voice handoff](voice-handoff.md) for the call flow.

## Isolation boundary

The entire Hermes process and its tools run in Docker as the caller's non-root
UID. The repository is mounted read-only at `/workspace`; `.local/hermes` is
mounted writable there and at the official image's `/opt/data` volume destination.
All host mount sources are inside this repo. HOME and HERMES_HOME point into that
local state. Agent outputs go under `.local/hermes/`, and the agent cannot change
the host launcher or source code. The image root filesystem is read-only; temporary
files use container tmpfs. Linux capabilities are dropped and privilege escalation
is disabled.

The host home, SSH credentials, desktop sockets, Docker socket, host PID namespace,
and host network namespace are not mounted or shared. Normal Hermes and chat
launches publish no ports; `voice-web` publishes only the loopback port above.
The buyer uses an internal Docker network with `gateway_mode_ipv4=isolated`, so
even a host service listening on every address is not available via a bridge
gateway. It has no default route. A separate unprivileged proxy allows HTTPS only
to `api.openai.com`, `api.ambiguous.ai`, `app.ambiguous.ai`, and the agreed supplier
hosts `multiply-cameo-clash.ngrok-free.dev` and
`supplier-codex-production.up.railway.app`, rejecting private,
loopback, and link-local DNS results. TLS stays end to end; the proxy has no
credentials or repo/state mount. Each launch creates and removes its own proxy
and private network. This requires Docker Engine 28 or later and fails closed on
unsupported engines. Do not put supplier-private state or unrelated personal
secrets inside the mounted repo.

Additional supplier website domains must be reviewed and added to
`runtime/hermes/egress.py` when Tapan provides them. There is deliberately no
unrestricted network fallback. Tools must honor the provided HTTP(S) proxy;
Node's native environment proxy support is enabled. The current API/CLI calls
work over HTTPS through that boundary.

We override the official image's root bootstrap/supervisor entrypoint to run its
installed Python/Hermes binary directly. This enables non-root execution and a
read-only image without installing a system service. `terminal.backend: local`
means local **inside the container**. Do not configure a host SSH or Docker backend.

`scripts/hermes smoke` verifies the actual running container: non-root UID, no
capabilities, no-new-privileges, writable local state, read-only source and image, no host home/socket,
and an external symlink target that cannot resolve. It makes no API calls.
`network-smoke` separately checks that direct host/internet connections fail,
unapproved domains receive a proxy denial, and unauthenticated OpenAI/Ambiguous
HTTPS requests reach their expected responses. It sends no API key or messages.

For supporting tools, use `scripts/hermes exec <command>`. For example:

```bash
scripts/hermes ambi identify
scripts/hermes ambi check
```

Install the pinned supporting CLI on the host, without package install scripts or
a global install, before launching the read-only runtime:

```bash
npm ci --prefix integrations/ambiguous --ignore-scripts --cache .local/npm-cache --no-audit --no-fund
```

See [Ambiguous setup](ambiguous.md) for workspace verification and task/notification
commands. CLI availability is setup evidence; an actual workspace task, remote
supplier exchange, and posted result are separate integration milestones.

The installed runtime's reasoning parser and Responses transport support Luna's
`max` setting. Run [model_smoke.py](../runtime/hermes/model_smoke.py) inside the
container to verify the configuration produces Luna, maximum reasoning, and
Priority on a mocked request without an API call.

Sources: [official Hermes Docker documentation](https://hermes-agent.nousresearch.com/docs/user-guide/docker),
[official Hermes config example](https://github.com/NousResearch/hermes-agent/blob/main/cli-config.yaml.example).
Network references: [Docker isolated gateway mode](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)
and [Node environment proxy support](https://nodejs.org/api/cli.html#node_use_env_proxy1).
