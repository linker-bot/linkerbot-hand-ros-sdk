^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Changelog for linkerbot_hand_msgs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This changelog follows Semantic Versioning. Every pull request that changes a
public message, service, constant, field meaning, or compatibility requirement
must update the ``Unreleased`` section. At release time, move those entries to
a dated version section and create a new empty ``Unreleased`` section.

Unreleased
----------

* **Breaking wire change:** add ``CommandCapability.returns_current_state`` for
  current-state command feedback, independently of protocol ACK and target
  arrival. This changes the enclosing ``HandCapabilities`` ROSIDL type. Rebuild
  all message consumers together; the next release must be major under the
  existing release policy. Published package versions remain unchanged here.

* Add ``GetRawValues`` for endpoint-selected raw reads, with a complete
  ``HandTelemetry`` response and stable failure fields. L6 uses it for
  ``get_limit_compensations``; configuration/limit services reuse the same fields.
  Clarify query, command-response and command-cache read modes: successful cache
  reads retain original sample metadata and can be stale. Adding this service
  itself does not alter existing interface fields; the separate command
  capability change above does.

2.0.0 (2026-09-11)
------------------

Every definition change in this release is additive: no existing message field
was removed, renamed or retyped, so source-level use of the 1.0.0 messages keeps
compiling.

**It is still a major release.** ``TelemetryCapability`` gained a field, and
that message is embedded in ``HandCapabilities``
(``TelemetryCapability[] telemetry``), so the ``HandCapabilities`` message hash
changed. A node built against msgs 1.0.0 therefore cannot exchange
``~/capabilities`` with a node built against 2.0.0.
Rebuild every package that uses these messages; a partial upgrade leaves that
topic silently unconnected.


* Add ``HandFaultStatusState`` and ``HandJointFaultStatus`` for the decoded
  per-joint fault bits a protocol profile documents. ``HandJointFaultStatus``
  keeps the exact protocol byte in ``raw`` next to the named flags
  (``hand_layer_stall``, ``actuator_layer_stall``, ``over_current``,
  ``over_temperature``, ``actuator_abnormal``, ``actuator_offline``,
  ``reserved_bits``), so a subscriber can re-check the bits without trusting the
  decoding.

* Add ``decoded_statuses`` to ``TelemetryCapability``, mirroring the Hand SDK
  field of the same name. It states whether samples on that channel carry
  decoded per-channel status objects, which a consumer needs in order to decide
  what to build before any device I/O.

* Add ``HandNormalForceResultant``, ``HandTactileSensorState``,
  ``HandTactileSensor`` and ``HandTactileField`` for O30 descriptor tactile
  data: the five-fingertip normal-force resultant, and the full descriptor
  stream with per-sensor geometry, the descriptor text, decoded fields and the
  exact raw bytes. Values are carried as reported by the device with no unit
  conversion.

* Compatibility: these are additive: no existing message definition changed, so
  existing subscribers keep working. Consumers must nevertheless rebuild
  ``linkerbot_hand_msgs`` to obtain the new types and the new
  ``TelemetryCapability`` field.

1.0.0 (2026-09-01)
------------------

* Add firmware-specific unsupported telemetry and parameter-save capability
  fields so clients can distinguish model support from current-firmware
  availability.
* Clarify device-command feedback as current device state rather than a target
  echo or protocol acknowledgement.
* Add publisher identity and timing metadata to command status records and
  publish changed command statuses in bounded batches.

0.99.0 (2026-08-28)
-------------------

* Introduce the independently discoverable ``linkerbot_hand_msgs`` package.
* Define typed capabilities, device information, joint state, telemetry,
  tactile, stall-protection, command-status, and management interfaces for the
  Hand SDK 1.0 contract.
* Keep protocol raw, percent, and optional physical-angle representations in
  separate fields with explicit validity metadata.
