# Tactile fields

[简体中文](zh/force.md) · [Manual](../README.md)

The latest SDK `main` exposes named tactile fields through `HandForceField` on
`~/state/force_<field>`. ROS publishes SDK cache data; it does not add CAN queries.
Build messages and consumers with consistent `main` ROSIDL definitions.

| Field | Meaning | L6/O6/L20/O20/L30 | L20Lite | O30 |
| --- | --- | --- | --- | --- |
| fn | Normal point/matrix raw values | Matrices | Matrices | Descriptor |
| fns | Normal resultant raw values | Unsupported | Five scalars | Descriptor |
| ft | Tangential point values | Unsupported | Unsupported | Descriptor |
| fts | Tangential resultant values | Unsupported | Five scalars | Descriptor |
| fd | Tangential point direction | Unsupported | Unsupported | Descriptor |
| fds | Tangential resultant direction | Unsupported | Five scalars | Descriptor |
| px | Proximity | Unsupported | Five scalars | Descriptor |

Read `capabilities.force_fields` or `HandCommandClient.force_field_capability(name)`.
O30 support is unknown (`support_known=false`) until descriptor discovery; afterward
`supported` describes installed sensors. `firmware_unsupported` marks a query disabled for this connection.

## Values and metadata

Each sensor has `sensor_name`, `present`, `raw`, `valid_values`, `unit` and `encoding`.
Missing sensors keep their identity with empty arrays, not fabricated zeros. Scalar raw arrays
have one element. L20Lite fds 255/reserved codes are retained but marked invalid; directions
are not converted to angles. Units and `scale_note` come from the SDK.

Each field has its own `meta` and `query_channel`. L20Lite fn/fns are independent acquisitions;
O30 fields from one native transaction share acquisition metadata. Use generation and sequence
to count samples; a validity/staleness update can republish a sequence without a new acquisition.

## Matrix and descriptor views

The force telemetry capability's `payload_projection` selects:

- `tactile_matrix`: `state/tactile` (`HandTactileState`), used by the six non-O30 models.
- `tactile_descriptor`: `state/tactile_sensors` (`HandTactileSensorState`), used by O30.
- Five scalar FnS values in one descriptor sample additionally produce `state/normal_force_resultant`.
- `raw_vector`: `state/force` (`HandTelemetry`); no current model declares this projection.

`HandTactileSensor` retains maximum/requested rows and columns, selected sensor, availability,
position mode and rectangle-fill metadata. These dimensions do not determine descriptor array
shape; use `descriptor`, `fields` and `raw_bytes`. Absent sensors are not zero-force measurements.
ROS never sums matrix cells to manufacture FnS or converts protocol force to newtons.
Independent scalar updates do not change matrix collection timestamps.

## O30 TASHAN_GATHER

For `Fn_F32_1;Ft_F32_1;Fd_U16_1;Px_U32_1`, each fingertip supplies 14 little-endian bytes:
one fn, ft, fd and px value. Zero Fn/Ft/Px is a valid present value; missing fingertips use
`present=false`. Maximum/requested dimensions of zero do not imply a missing sensor.

Fn/Ft retain the reported force unit; Fd/Px remain unknown unless explicitly provided.
Fd 65535 is preserved as U16 without angle conversion or a ROS-defined invalid-code rule;
`valid_values` carries the SDK decision. No FnS means no new `force_fns` or normal resultant.
After sensor-layout changes, use updated capabilities and sample metadata; topic existence alone does not prove support.

## Polling

All tactile rates default to zero. For L20Lite, independently request matrices, normal resultants
and proximity:

```yaml
force_hz: 0.0
force_fn_hz: 20.0
force_fns_hz: 10.0
force_px_hz: 5.0
```

`force_ft_hz`, `force_fts_hz`, `force_fd_hz` and `force_fds_hz` follow the same rule.
Explicit positive rates for unsupported fields fail validation. Zero disables that field's request,
but a shared query can still return it.

`force_hz` requests available fn + fns. Do not combine positive `force_hz` with positive fn/fns-specific
rates; switch using an atomic parameter update. L20Lite performs two independent queries;
O30 performs one descriptor transaction at the maximum requested field rate.
For TASHAN_GATHER, fn=10, ft=20, fd=15, px=5 Hz requests one 20 Hz transaction, not 50 Hz.

`publish_rate_hz` controls idle age/stale checks; zero pauses ROS publication. While enabled,
SDK changes wake publication immediately. Diagnostics expose
`force_<field>_requested_hz/query_hz/achieved_hz` and `query_channel`.
Do not add shared-field sample rates to estimate bus traffic; use physical `channel_*` counters.
