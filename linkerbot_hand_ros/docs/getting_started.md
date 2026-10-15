# Hand ROS 2 User Manual

`linkerbot_hand_ros` connects LinkerHand dexterous hands to ROS 2. It provides device discovery, angle control, state and tactile feedback, and management services. Supported models are L6, O6, L20Lite, L20, O20, L30 and O30.

> [!TIP]
> Start with installation and the first state read, then follow the guide for your model.

## Quick start

[Quick start](quick_start.md): install Python dependencies and ROS packages, connect one hand and read its first angles.

- Ubuntu 22.04 / Python 3.10: use [Humble](quick_start.md#ubuntu-2204-humble).
- Ubuntu 24.04 / Python 3.12: use [Jazzy](quick_start.md#ubuntu-2404-jazzy).

Both use the same `main` sources and ROS interfaces. Install and build for your distribution,
then [load its environment](quick_start.md#4-load-each-terminal) before following the connection and feature guides below.

## Connect devices

[Prepare the communication interface](connection.md), then choose a connection method:

- [Manual connection](manual_connection.md): specify the model, side and adapter settings.
- [Automatic connection](discovery.md): discover one or multiple hands and save a reusable deployment.

## Device features

All models provide identity and capabilities, angles, speed settings, current and temperature data. Available endpoints follow the connected device's `capabilities`.

| Model | Features |
| --- | --- |
| [L6](l6.md) | Angles, speeds, torque mode, gains, limit compensation, tactile data |
| [O6](o6.md) | Angles, speeds, accelerations, tactile data, O6 GUI |
| [L20Lite](l20lite.md) | Angles, speeds, accelerations, matrices and resultant/direction/proximity fields |
| [L20](l20.md) | Angles, speeds, tactile data, fault clearing |
| [O20](o20.md) | Angles, speeds, configuration readback, tactile data, fault clearing |
| [L30](l30.md) | Angles, speeds, tactile data, enable/disable, calibration |
| [O30](o30.md) | Angles, speeds, accelerations, torque limits, motion times, descriptor tactile data |

[Model differences](models.md) explains configuration readback, units and sensor differences.

## Developer integration

- [Control and Python examples](examples.md): read state, send targets and reuse `HandCommandClient`.
- [Application integration](business_integration.md): readiness, command status, arrival and recovery.
- [ROS 2 API](ros_api.md): topics, services, QoS and error semantics.
- [Message fields](messages.md), [tactile data](force.md), [lifecycle and parameters](configuration.md): reference details.

## Further information

- [Troubleshooting](troubleshooting.md): installation, connection, state and control problems.
- [Update SDK and ROS](update.md): update sources and rebuild messages and driver.
- [Frequency benchmark](frequency_benchmark.md): distinguish command dispatch, device acquisition and ROS reception.

[简体中文](zh/getting_started.md)
