# Frequency benchmark

`frequency_benchmark` compares two workloads: continuous angle commands with angle feedback, and the same workload with complete tactile transactions. By default it holds the first valid percent pose, but still sends real commands continuously; this is not a read-only test.

## Prerequisites

- Follow [quick start](quick_start.md) or [update](update.md); verify active state, identity and valid current-generation angles.
- Stop other target publishers and active query programs. Use one physical channel per hand.
- Verify bus configuration, termination, device IDs, emergency stop and clearance separately.
- Set sufficient `command_rate_hz` at startup; the benchmark does not change this static parameter.

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l6 side:=left command_rate_hz:=250 \
  transport_json:='{"backend":"socketcan","channel":"can1"}'
```

## Angle commands and feedback

Run each candidate for 180 seconds, repeated three times:

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-feedback query_only \
  --angle-rates 50 100 150 200 \
  --duration 180 --repetitions 3
```

The tool atomically sets `angles_hz`, `angle_feedback`, `publish_rate_hz` and `diagnostic_rate_hz`, clears all tactile field rates, then sets `force_hz`. Diagnostics default to 1 Hz. Raising `--diagnostic-hz` adds observation cost; record it when comparing results.

Without `--angle-values`, the tool first obtains a baseline using `query_only + 100 Hz`, then applies candidate settings. This read occurs outside the timed window. Explicit targets and `--no-configure-driver` skip this preparation.

| Policy | Workload and metric |
| --- | --- |
| `query_only` | Active queries; compare with an identical set-plus-query workload |
| `command_feedback_only` | Device command feedback; requires `returns_current_state` |
| `adaptive` | Prefer feedback and query gaps |

Policies have different bus workloads. Test them separately rather than reporting one combined limit.

## Angles with complete tactile data

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-rates 20 50 100 150 200 \
  --tactile-hz 30 \
  --duration 180 --repetitions 3
```

30 Hz means 30 complete multi-finger samples per second, not fingers, fields or CAN fragments. The tool selects matrices or descriptors using `payload_projection`. Missing identities or incomplete fields invalidate a sample; explicitly absent sensors may retain identity and empty data.

L20Lite `force_hz` requests independent fn and fns transactions, while tactile success counts matrices. For a matrix-only test, manually set `force_fn_hz` and use `--no-configure-driver`. O30 FnS resultants use separate `resultant_cache/resultant_ros` counters. Descriptors without FnS still support tactile benchmarking, without resultant samples.

Warmup should cover the first complete tactile read; initial metadata acquisition and cached acquisition have different costs. This tool does not establish units, pressure response or mechanical arrival. Excess transaction cost can cause parameter rejection or runtime timeouts; a higher ROS publication rate cannot compensate.

## Optional targets and motion

Enable oscillation only after checking direction, speed, limits and clearance. This example applies a three-percent-point amplitude to joint index 2:

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-rates 50 100 --angle-amplitude 3 --joint-index 2 --angle-period 2 \
  --duration 180 --repetitions 3
```

Use `--angle-values 50 50 50 50 50 50` for an explicit six-joint baseline; the count must match the device. For externally fixed settings, use `--no-configure-driver --angle-rates 100`; the caller must provide sufficient polling, publication and diagnostics rates.

## Metrics and acceptance

`ros2 topic hz` observes ROS reception only. It cannot replace acquisition or dispatch counters. The tool records:

- Local publication, driver reception, SDK `ACCEPTED`, actual `DISPATCHED` and protocol-terminal rates.
- P50/P95/P99 for publication-to-reception, reception-to-admission, admission-to-dispatch and publication-to-dispatch latency; publication interval P95.
- Complete queries (`completed_reads`), command feedback, policy-counted feedback, SDK cache sequence updates and valid ROS reception rates.
- FAILED, SUPERSEDED, generation changes and pending/timeout/drop/route-miss/bus-error deltas.

Commands are deduplicated by `(client_id, user_sequence, stage)`. Even a final ACK requires a DISPATCHED transition in `transitions[]` to count as sent. State generation and sequence distinguish new samples. Queries, feedback and reports are separate evidence; `origin` identifies the current source.

Default `minimum_ratio=0.9` requires each command stage and angle-feedback/cache/ROS rate to reach 90% of target. Query-only also requires completed-query rate; command-feedback-only requires command-feedback rate; adaptive may combine both. Complete tactile read/cache/ROS rates must each meet the tactile target.

A round also requires no FAILED commands, missing or reversed latency timestamps, or generation changes; `pending_commands=0` after drain; and no increase in consecutive errors, angle/tactile timeouts, transport drops, route misses or bus errors. SUPERSEDED is reported separately and constrained by actual-dispatch acceptance.

A candidate is stable only after three passing rounds. Testing stops at the first failure by default; `--continue-after-failure` permits higher candidates. Disconnects or generation changes abort the test; establish a new baseline before restarting.

## Exit codes and records

| Code | Meaning |
| --- | --- |
| `0` | All candidates and rounds passed |
| `2` | Test completed with at least one failed candidate |
| `1` | Invalid startup, parameters, state or capabilities |
| `130` | User interruption |

Record driver logs, `/diagnostics`, CPU/RSS, thread/FD counts and `ip -details -statistics link show canX`. Comparisons with raw SocketCAN or Python SDK must use identical requests, reply validation, target updates and duration.

[Back to overview](getting_started.md) · [简体中文](zh/frequency_benchmark.md)
