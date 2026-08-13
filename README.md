# hass-zowiebox

Home Assistant integration for [ZowieTek ZowieBox](https://www.zowietek.com/) NDI
HDMI encoder/decoders. Local polling — every entity reflects what the device
itself reports, so changes made on the box (web UI, physical) show up in HA
within one poll interval.

## Why (vs. fire-and-forget HTTP automations)

The box's `/streamplay` API group — including NDI source enumeration and
decoder state — is **rejected entirely while the box is in Encoder mode**
(`"workmode is not support!"`, status `00004`). Any state kept HA-side
therefore drifts the moment the box is changed behind HA's back. This
integration polls the device for truth instead:

- **Work mode** read from `get_workmode_id` every poll.
- **Encoder signaal** binary sensor is gated on the device's own work mode:
  it is `on` only when the box is in **Encoder** mode *and* an HDMI input
  signal is present — a decoder-mode box never reports a phantom encoder
  stream.
- **NDI decode sources** are discovered via mDNS (`_ndi._tcp.local.`) through
  Home Assistant's shared zeroconf — the only mechanism that works regardless
  of the box's mode.

## Entities (per box)

| Entity | Description |
|---|---|
| `binary_sensor` Encoder signaal | Encoder mode AND HDMI signal present (resolution/framerate/audio as attributes) |
| `binary_sensor` Encoder signaal 5 seconden | Same, but only after the signal has been steady for 5 s (debounces source switches) |
| `select` Werkmodus | Encoder / Decoder; switching also sets HDMI loop-out (Encoder → loop-through on, Decoder → decoded output) |
| `select` Decode bron | NDI source to decode, options live from LAN mDNS (own stream filtered out); selecting one implies Decoder mode |
| `sensor` Ingangsresolutie | Current HDMI input format (e.g. `1080p59.94`) |
| `button` Herstarten | Reboot the box |

The device unique_id is the box's MAC (from `get_lan_info`), so a DHCP address
change won't duplicate devices; update the host via reconfigure if it moves.

## Install

HACS → custom repository `daveyijzermans/hass-zowiebox` (integration) →
download → restart HA → Settings → Devices & services → Add integration →
ZowieBox → enter the box IP. Poll interval (default 5 s) is configurable per
box via the entry's options.

## API notes

Protocol: `POST http://<box>/<endpoint>?option=getinfo|setinfo&login_check_flag=1`
with body `{"group": ..., "opt": ..., "data": {...}}` (ZowieTek API v1.0 PDF).
Quirks handled here:

- `get_workmode_id` returns `workmode_id` at the response **top level** (not
  under `data`); the getter is undocumented in the PDF (recovered from the
  box web UI bundle).
- All `/streamplay` calls fail with status `00004` in Encoder mode — the
  coordinator only queries decode state when the device reports Decoder mode.
- `rsp` may be `succeed` or `success`; status `00000` is OK, `00010` is the
  OK response to reboot.
