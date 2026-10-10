# Automatic discovery and reusable deployment

Manual launch and old ROS parameter YAML remain available. Discovery reads
identity through the source Hand SDK, closes probes, then constructs each driver
through its candidate factory. It does not change host CAN settings or send extra
motion, enable, fault-clear or calibration commands. Use one hand per channel.

## Three startup modes

```bash
# Manual single hand (existing)
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l6 side:=left \
  transport_json:='{"backend":"socketcan","channel":"can0"}'

# Exactly one unique verified hand, keeping /linkerbot_hand
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true

# All verified hands in scope, save ./hands.yaml, then activate the group
ros2 launch linkerbot_hand_ros multi_hand.launch.py discover:=true
```

Single-hand zero/multiple/incomplete candidates fail without choosing the first
hand. Multiple candidates produce a list and copyable commands to limit scope:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true channels:=can0
```

`channels` is a comma-separated list of SDK report names: `can0`,
`pcan:PCAN_USBBUS1`, `slcan:COM5`, `minicanfd:0:0`. Missing interfaces do not
trigger fallback. Discovery cannot mix explicit `model`, `side`, `transport_json`;
single-hand runtime arguments (e.g. `angles_hz:=50`) and `namespace` still apply.
Single-hand discovery follows ROS namespace rules: relative paths are under the
enclosing `PushROSNamespace`, while absolute paths stay fixed.

Multi-hand discovery needs at least one verified candidate. It shows interface,
model, physical side, backend, then assigned namespace. Illustrative output:

```text
can0: L6, left, socketcan [verified]
can1: O6, right, socketcan [verified]
binding namespace=/l6l -> can0 (L6)
binding namespace=/o6r -> can1 (O6)
configuration saved: /working/directory/hands.yaml
```

Partial identities and backend failures remain visible. Multiple responding
endpoints on a selected channel, duplicate bindings or unresolved probe cleanup
block startup. Any selected node activation failure rolls back the group.
Discovery startup failures return a nonzero launch exit status for scripts.

## Save once, reuse fixed roles

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py \
  discover:=true channels:=can0,can1 output:=./hands-lab.yaml

ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=./hands-lab.yaml
```

Default output is `hands.yaml` in the launch working directory; its absolute path
is printed. Existing files are rejected before scanning. Export is atomic and
never overwrites a file, including a creation race. A required write failure
prevents activation. Saving and activation are reported separately; the saved
configuration remains available if later activation fails.

`config` accepts old ROS parameter files and generated discovery deployments.
New files use `schema: linkerbot_hand_ros.discovery`, `version: 1`, `autostart`,
`discovery` settings and a `hands` list of `namespace`, `match`, `parameters`.
Unknown versions/keys, duplicate keys/namespaces/channels fail validation.
These deployments must be loaded through launch, not ROS `--params-file`.

SDK aliases provide initial namespaces such as `/l6l`. Edit the saved namespace
for a business role. New multi-hand discovery puts aliases under the container
namespace: `PushROSNamespace("/robot")` produces `/robot/l6l` and `/robot/o6r`.
These absolute paths are saved once; loading under another parent keeps them.
Edit or regenerate the deployment to relocate roles. Internal node names and
namespaces are protected from process-wide `__node`/`__ns` remaps while global
parameters (including `use_sim_time`) and topic remappings remain available.
Old ROS parameter files evaluate launch substitutions before ROS validation;
new discovery deployments use their static schema.

Loading rescans saved resources and uniquely matches only
saved roles; new ambient devices do not join and alias renumbering does not
change roles. Missing/replaced identities fail. Available serial/product identity
is combined with interface, wire protocol and endpoint constraints. Missing or
nonunique identity cannot prove a globally permanent physical device ID.

The file saves validated inputs, not factory objects, cleanup callbacks or old
fingerprints. Fresh SDK factories preserve FD recipes, O30 nondefault addresses,
L30 Node IDs and the current scan fingerprint across open/retries/recovery.
L30 physical side is shown while constructor side remains not applicable.
Generated selectors do not lock firmware versions; stop/cleanup before upgrades
and start a new discovery session.

New discovery defaults to `autostart=true`; file startup preserves its saved
value unless explicitly overridden. `autostart:=false` still scans/saves, then
keeps unconfigured lifecycle nodes running for external management. It does not
open runtime devices or exit after scanning. Discovery/saving is not control
readiness: check active, runtime verified capabilities and current state.
Multi-hand paths use the saved namespace, e.g. `/l6l/linkerbot_hand/state/angles`.

## Advanced settings

Both discovery launch files accept `discovery_config:=/path/to/settings.yaml`,
containing SDK `DiscoveryConfig` fields without a deployment schema:

```yaml
backends: [socketcan]
channels: [can0, can1]
total_timeout_s: 30.0
l30_node_ids: [13]
o30_request_ids: [23]
```

PCAN/SLCAN sections support native `channels`, `bitrate`, `data_bitrate`,
`probe_protocols: [can, can_fd]`, scalar `bus_options` and `can.BitTimingFd`
fields under `fd_timing`. SLCAN `bus_options.tty_baudrate` is the serial rate,
separate from CAN rate. MiniCANFD supports `library_path`, device-to-channel
`linux_channels` and SDK `CANFDConfigOptions` under `config`. Relative library
paths resolve against the settings/deployment directory. Per-hand `parameters`
use existing runtime names; manual product/transport fields are forbidden.
Conflicting launch/file channel scopes fail instead of expanding scope.

Backend omission uses SDK platform defaults: SocketCAN/MiniCANFD on Linux,
PCAN/SLCAN/MiniCANFD on Windows. Libraries, permissions, configured interfaces
and adapter firmware must be available. The scan budget is soft; vendor calls
and required cleanup can take longer. No runtime rescan, hotplug substitution
or interactive prompt is provided. Automated tests use source SDKs/in-memory
peers; Windows and adapter/hand hardware require separate acceptance.
