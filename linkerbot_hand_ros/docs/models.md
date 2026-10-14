# Model differences

Models share the same ROS messages and client; endpoints follow device capabilities. Start with the feature guide for your model.

| Model | Joints | Bus | Features |
| --- | ---: | --- | --- |
| [L6](l6.md) | 6 | CAN | Angles, speeds, torque mode, gains, limit compensation, tactile data |
| [O6](o6.md) | 6 | CAN | Angles, speeds, accelerations, tactile data, O6 GUI |
| [L20Lite](l20lite.md) | 10 | CAN | Angles, speeds, accelerations, matrices and resultant/direction/proximity fields |
| [L20](l20.md) | 16 | CAN | Angles, speeds, tactile data, fault clearing |
| [O20](o20.md) | 16 | CAN FD | Angles, speeds, configuration readback, tactile data, fault clearing |
| [L30](l30.md) | 17 | CAN FD | Angles, speeds, tactile data, enable/disable, calibration |
| [O30](o30.md) | 20 | CAN FD | Angles, speeds, accelerations, torque limits, motion times, descriptor tactile data |

## Capabilities and units

- `capabilities.joints` defines joint order, raw ranges and percent endpoints.
- `capabilities.commands`, `telemetry` and `operations` define commands, state and management services.
- `firmware_unsupported_telemetry` identifies queries rejected by firmware in the current connection.
- Raw values retain protocol data. Check `raw_unit`, `raw_scale_note` and `unit_confidence` for physical-unit information.

Live current, speed and torque differ from current limits, configured speeds and torque limits. O30 measured torque also differs from L6 raw output/mode.

## Three configuration read modes

| read_mode | Meaning | Examples |
| --- | --- | --- |
| `query` | Request a fresh device sample | O6 configured speeds, O30 motion times |
| `command_response` | Last valid device write reply | L6 configured speeds, O6 current limits, L20Lite settings |
| `command_cache` | Locally dispatched command cache | L30 configured speeds and current limits |

Cache reads preserve original acquisition time and sequence; `success=true` can still mean `stale=true`. Recovery invalidates old-generation caches. Missing samples never cause an automatic write to manufacture readback.

## L6

See [L6 feature guide](l6.md#model-details-and-management).

## O6

See [O6 feature guide](o6.md#model-details-and-management).

## L20Lite

See [L20Lite feature guide](l20lite.md#model-details-and-management).

## L20

See [L20 feature guide](l20.md#model-details-and-management).

## O20

See [O20 feature guide](o20.md#model-details-and-management).

## L30

See [L30 feature guide](l30.md#model-details-and-management).

## O30

See [O30 feature guide](o30.md#model-details-and-management).

[Back to overview](getting_started.md) · [简体中文](zh/models.md)
