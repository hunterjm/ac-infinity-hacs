# AC Infinity Bluetooth

Custom Home Assistant integration for AC Infinity controllers and connected UIS loads.

Requires Home Assistant 2026.9+ and `ac-infinity-ble==1.0.0`. Home Assistant installs
the pinned library requirement automatically. For development, build and install
a matching library wheel before setting up the integration.

## Installation and updates

Install **AC Infinity** through HACS, then restart Home Assistant and add the
integration under Settings → Devices & services. If it is not in your HACS
catalog, add `https://github.com/hunterjm/ac-infinity-hacs` as a custom repository
with category **Integration**.

HACS discovers updates from published GitHub releases. Install the offered update
and restart Home Assistant; existing config entries migrate automatically.
Home Assistant versions older than 2026.9 must remain on integration 1.x.

## Controls

- Existing controller fan and temperature/humidity/VPD entities retain their IDs.
- Detected physical fan ports expose fan speed and power controls.
- Detected lights expose power and brightness controls.
- Outlets expose manual power controls.
- Humidifiers, dehumidifiers, heaters and air conditioners expose manual power
  and native output-level controls. These do not implement thermostat setpoints,
  app schedules, AI recipes, or secondary device functions.
- Cloudcom sensors expose measurements without fan controls.

Only reported connected ports receive entities. An unplugged or changed load
makes its previous entities unavailable. Wi-Fi-only firmware may not expose
operational Bluetooth control even when the APK contains a Bluetooth codec.

The protocol source of truth is AC Infinity Android APK 2.0.8. See the library's
[protocol documentation](https://github.com/hunterjm/ac-infinity-ble/blob/main/docs/protocol-validation.md)
for wire formats, model dispatch and remaining hardware checks.

Multiple fans and mixed loads on one controller have independent port entities
and commands, grouped under the controller's device entry. Names include the
common model name and advertised identity; known retail model numbers are also
provided. Custom names and existing entity IDs are preserved.

The original Fan entity controls the controller-wide channel. It is not an
average or mirror of the individual ports: changing Port 1 Fan does not change
the controller-wide saved setting. Controller-wide commands can affect connected
loads, so use port entities for independent control.

Firmware/software and hardware revisions are read from optional Bluetooth Device
Information characteristics during an existing connection. The app's displayed
software revision is preferred; protocol revision is kept as a separate attribute.
Missing revisions remain unknown. Reload the integration to refresh cached
revisions after a firmware update.

Config entries migrate automatically to schema 1.3, including older stored
identity data and generated titles. See the library's
[architecture](https://github.com/hunterjm/ac-infinity-ble/blob/main/docs/architecture.md)
for the module boundaries, identity policy, and migration details.

## Connection lifecycle

Commands serialize connection, subscription, writes and retries. The integration
refreshes Home Assistant's Bluetooth route before reconnecting and releases the
connection after five idle seconds. Unload, shutdown, failed setup and config-flow
failures await cleanup.

## Polling

Climate updates arrive through advertisements. Port telemetry has a 30-second
freshness target; saved settings are read on startup, when loads change, and every
five minutes. Failed background polls back off up to five minutes; user commands
bypass that delay. Polling follows Home Assistant Bluetooth events and requires a
connectable route, so these intervals are freshness targets rather than fixed timers.
Unload cancels an active poll and awaits connection cleanup.

Selecting OFF preserves the saved minimum, which may allow physical fan movement.
Actual speed is reported independently of mode. On newer protocols, manual-speed
writes preserve the separate saved maximum packed into the same parameter.

## Development and validation

For troubleshooting, enable debug logging from the AC Infinity integration page.
This includes the Bluetooth library's command, notification and connection logs.
Disable debug logging after reproducing the issue, and review the downloaded log
for device identifiers before sharing it.

With both repositories checked out as siblings, run lightweight unit tests on
Python 3.12 or newer:

```shell
python -m pip install -e ../ac-infinity-ble -r requirements-test.txt
python -m pytest tests
ruff check custom_components tests tests_ha tests_release
ruff format --check custom_components tests tests_ha tests_release
```

For the real Home Assistant 2026.9.3 API tests, use Linux and Python 3.14:

```shell
python -m pip install -r requirements-ha-test.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests_ha
```

Run `tests/` and `tests_ha/` in separate processes: the former uses lightweight HA
API doubles; the latter uses real HA entry, registry and coordinator classes with
mocked Bluetooth and platform forwarding. Tests cover migration, metadata,
unload/reload identity, poll cancellation and refreshed adapter/proxy selection.
These tests do not require a Bluetooth adapter.

CI installs the published library requirement from the manifest. To test a library
change before publication, dispatch CI with `library_ref` pointing to a branch,
tag or commit; CI builds that wheel and checks it matches the manifest pin.
Publish the required library version before releasing this integration.
Ruff owns Python linting, import sorting and formatting; its conservative rules
match the library's configuration.

Use Conventional Commit PR titles and squash merges. Successful `main` builds
automatically version and publish releases; see [the release procedure](RELEASING.md)
for version selection, HACS discovery, and recovery. Release tooling has separate
tests that create local tags without pushing or publishing:

```shell
python -m pip install -r requirements-release.txt
python -m pytest tests_release
```

See the [testing guide](https://github.com/hunterjm/ac-infinity-ble/blob/main/docs/testing.md)
for coverage boundaries and a reproducible hardware validation procedure. The
[protocol documentation](https://github.com/hunterjm/ac-infinity-ble/blob/main/docs/protocol-validation.md#compatibility-evidence)
distinguishes hardware-confirmed Controller 69 Pro behavior from APK-derived
support for other families.
