# Prepare the communication interface

Complete [installation](quick_start.md) first. Use one hand per physical CAN/CAN FD
channel; use a separate channel for each hand in a multi-hand deployment.
The ROS installation guide targets Ubuntu 22.04/Humble or Ubuntu 24.04/Jazzy. Windows adapter configuration follows
SDK capabilities, but Windows ROS and hardware operation require platform validation.

## SocketCAN on Linux

Install the adapter's driver/firmware until Linux exposes a network interface such as `can0`.
A serial port alone does not provide a SocketCAN FD interface. Configure the link before
starting a driver; discovery does not bring links up or alter their bitrates.

L6, O6, L20Lite and L20 use classic CAN at 1 Mbit/s:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

O20, L30 and O30 use CAN FD. The standard SDK setup uses 1 Mbit/s arbitration and
5 Mbit/s data:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on
sudo ip link set can0 up
ip -details -statistics link show can0
```

O20/L30 require the declared data bitrate. O30 uses BRS off; when its capability does
not constrain data bitrate, ROS adopts the existing link's value if none is supplied,
falling back to 5 Mbit/s when it cannot inspect the link. The interface must still be
configured for FD at the correct arbitration rate.

## Vendor adapters

MiniCANFD requires the vendor driver and `libcanbus.so` (Linux) or `HCanbus.dll` (Windows). PCAN requires PCANBasic and its driver; SLCAN FD requires verified CANable 2.0 FD firmware. Match library architecture to the Python process.

Linux adapters exposed as `can0` use SocketCAN. SDK adapter support on Windows does not establish a validated Windows ROS deployment.

## Choose a connection method

- [Manual connection](manual_connection.md): supply a known model and interface.
- [Automatic connection](discovery.md): identify one hand or discover multiple hands and save a deployment.

Before rescanning or using an SDK script on the same device, stop the old driver and perform deactivate and cleanup.

[Back to overview](getting_started.md) · [简体中文](zh/connection.md)
