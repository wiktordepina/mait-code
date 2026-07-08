# The Bridge

The **Bridge** gives the quick-capture inbox a way in from anywhere — a phone
on a dog walk, another machine — instead of only a terminal on one box. It
pulls captures from a self-hosted channel into `inbox.db`, where `/triage`
routes them onward, with no daemon and no background process: the session-start
hook drains whatever accumulated since it last looked, and stops.

The transport is pluggable. **ntfy** ships today; the channel interface is
written so a new transport (MQTT, a Telegram bot) is a subclass plus a registry
line, not a rewrite of the plumbing.

## Off by default

The Bridge is **disabled until you switch it on**, deliberately: enabling it
allows outbound network access, which isn't always permitted (a work machine
under a corporate policy). While disabled it makes *zero* network calls — the
drain short-circuits before any request. Turn it on only where that access is
allowed, per machine.

Enable and configure it from the home hub — **System ▸ ↗ Configure Bridge** —
or launch the editor directly. The form collects the channel's settings and
offers a **Test connection** button that probes them before you save.

## Setting up ntfy

The Bridge expects a private [ntfy](https://ntfy.sh) topic. ntfy self-hosts as
a single container, so the home server is the natural place for it:

```bash
docker run -d --name ntfy -p 80:80 \
  binwiederhier/ntfy serve
```

Pick a **private, unguessable capture topic** (it's the address captures are
published to and drained from — treat it like a secret), and, on a protected
server, mint an access token. Then in the Bridge editor:

| Field | Value |
|-------|-------|
| **Server URL** | Base URL of your ntfy server, e.g. `https://ntfy.example.org` |
| **Capture topic** | The private topic, e.g. `mait-capture-7f3a9c` |
| **Access token** | A bearer token for a protected topic (leave blank if open) |

Set **Status** to *enabled*, **Test connection** to confirm the server is
reachable and the token works, then **Save**.

## Capturing

Anything published to the capture topic becomes an inbox item on the next
drain. Publish however suits the moment:

```bash
# from any machine
curl -d "ring the vet about Cody's booster" https://ntfy.example.org/mait-capture-7f3a9c
```

On a phone, the ntfy app, an Android [HTTP Shortcut](https://http-shortcuts.rmy.ch/)
or an Apple Shortcut turns the share sheet into the same authenticated POST —
capture from anywhere, triage at your desk.

## Draining

Draining happens two ways, both idempotent (a per-machine watermark tracks what
each machine has already seen):

- **Automatically**, at session start — the hook drains before it builds the
  brief, so fresh captures show up in the inbox count straight away.
- **Manually**, any time: `mc-tool-inbox drain`.

Captured items land in the inbox exactly as if typed there, and `/triage`
routes them to the board or memory as usual.

## Health

`mait-code doctor` reports the Bridge: *disabled* when off (the safe default),
and a **warning** — never a failure — when it's enabled but a required field is
blank, so a half-configured Bridge degrades to a no-op rather than a broken
session.

The channel config lives in `bridge.json` under the data dir; the drain
watermark lives beside it in `bridge-state.json` and is never synced between
machines.
