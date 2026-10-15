# Linkerbot Hand ROS 2 user manual

English | [简体中文](README_zh.md)

Control L6, O6, L20Lite, L20, O20, L30 and O30 hands through ROS 2 topics and services.
Each driver owns one `HandDevice`; the latest Hand Python `main` handles connection,
polling and command scheduling. Applications use ROS interfaces without opening CAN again.

## Quick start

[Website manual overview](docs/getting_started.md)

[Install and read the first angles](docs/quick_start.md): choose Humble or Jazzy, install sources,
build the packages and read device state.

## Connect a hand

- [Prepare interfaces](docs/connection.md), then [connect manually](docs/manual_connection.md): SocketCAN, MiniCANFD, model and side.
- [Automatic discovery and multi-hand deployment](docs/discovery.md): connect, save and reuse device bindings.
- [Adapter examples](docs/discovery_examples.md): PCAN, SLCAN, MiniCANFD and fixed deployment templates.

## Device features

- [Seven-model ROS guide](docs/models.md): joint counts, speed/acceleration, current/torque and special operations.
- [Commands and Python examples](docs/examples.md): publish targets, read settings and use a persistent client.
- [Tactile fields](docs/force.md): matrices, normal/tangential fields, proximity and polling.
- [O6 GUI](docs/gui.md): URDF preview and explicitly enabled hardware control.

## ROS reference and integration

- [ROS API](docs/ros_api.md): topics, services, message semantics and QoS.
- [Lifecycle and parameters](docs/configuration.md): defaults, live rates, timeouts and recovery.
- [Application integration](docs/business_integration.md): readiness, feedback, arrival and cleanup.
- [Client waits](docs/client_waits.md): synchronous/asynchronous waits and executor requirements.
- [Frequency benchmark](docs/frequency_benchmark.md): distinguish dispatch, sampling and publication rates.

## Maintenance

- [Troubleshooting](docs/troubleshooting.md)
- [Update SDK and ROS](docs/update.md)
- [Local development checks](../DEVELOPMENT.md) (Chinese)
- [Hand Python manual](https://github.com/linker-bot/linkerbot-hand-python-sdk/blob/main/docs/en/src/reference/README.md)

Use the connected device's capabilities for joint order, ranges and interface support.
Acceptance, dispatch, protocol acknowledgement and mechanical arrival are separate stages;
arrival requires valid feedback from the current connection generation.
