# 发现与部署排障

先确认平台：Linux 为 SocketCAN（经典 CAN/CAN FD）、MiniCANFD；Windows 为 PCAN（经典 CAN/CAN FD）、MiniCANFD、SLCAN（CAN FD）。`backends` 不会启用其他平台的来源。出现 `backend ... is unavailable on this platform` 时先选择本平台模板；Linux 下若适配器已经暴露为 SocketCAN 网络接口，应使用 SocketCAN，串口 SLCAN 模式不属于此入口范围。

先保留同一次启动的扫描摘要、失败行及最后的生命周期错误。关注 `operation`（SDK 操作）、`backend`、`channel`/`native_channel`、`protocol`、角色 namespace 和配置路径；`stage` 是容器阶段，`cause` 是原始异常。SDK 不提供的字段不会推测，`backend=selection` 表示接口筛选阶段，不是物理适配器。配置模板见[配置示例](discovery_examples.md)。

以下是日志格式示例，不代表现场扫描结果：

```text
discovery unavailable: requested discovery channel was not enumerated (operation=enumerate_selection_unavailable error_type=DiscoveryError backend=selection native_channel='can0')
activate failed: [identity_mismatch] ... (node=/left_hand/linkerbot_hand backend=socketcan channel='can0' protocol=can scheme=classic_can_id request_id=0x28 response_id=0x28 extended_id=False)
```

## 配置或文件错误

- `discovery_config=...` 指向高级扫描设置；`deployment_config=...` 指向可复用部署。`hands[0]` 为从 0 开始的列表位置，后面的 namespace 定位角色。检查未知/重复字段、参数类型、namespace 和接口冲突。
- 高级设置须用 `discovery_config`，schema/version 1 的部署须用 `config`，不能作为 ROS `--params-file`。ROS 参数文件支持 launch substitution。
- `output already exists` 在扫描前拒绝；复用文件使用 `config:=...`，重新发现使用新的 output 路径。写失败时检查父目录存在及写权限，不删除原文件来绕过保护。

## `unavailable`：指定接口没有枚举到

先按失败行定位接口。Linux SocketCAN 用以下只读检查确认名称、UP、CAN/FD 和速率：

```bash
ip -details link show can0
```

PCAN 高级配置中的原生名称是 `PCAN_USBBUS1`，全局筛选名是 `pcan:PCAN_USBBUS1`。SLCAN 对应串口路径或 COM 端口；MiniCANFD 使用枚举索引。核对连接和配置后再启动；指定接口缺失不会自动改扫别的接口。接口设置由宿主环境负责。

## 没有候选、候选不唯一或 `partial`

若同时存在后端失败，先处理后端失败，不能将其解释为“设备不存在”。接口已可用时，检查手的供电、接线、终端、协议和速率。单手多候选用正确的 `channels` 限定，或改用多手入口；PARTIAL 的 `problem code: message` 表示身份缺失，不会自动补侧别或激活。L30 Node ID、O30 非默认请求 ID 须在已知范围内配置，不猜测身份。

## 厂商库加载、驱动或权限失败

SDK 错误码可能按枚举阶段命名，具体原因见 `error_type`、message 和 cause。检查实际库路径、进程/库位数以及依赖；Linux MiniCANFD 需要真实 `libcanbus.so` 和 USB 访问权限，Windows 需要正确 `HCanbus.dll`、厂商 USB 驱动与其运行库。Windows PCAN 需要对应 PCANBasic/驱动，SLCAN 需确认实际 COM 端口和占用状态；可在设备管理器核对。Linux MiniCANFD 的 USB 权限可只读检查：

```bash
id
lsusb
ls -l /dev/bus/usb
```

按系统的设备权限管理方式解决访问问题；不要用全局放开设备权限或强制管理员运行代替原因定位。相对库路径以设置/部署文件目录为基准，库不随 ROS/SDK 分发。

## `busy`：资源仍被占用

`deactivate` 只停止命令和轮询，连接租约到 `cleanup` 才释放。对自己管理的旧节点有序失活、cleanup 并退出后再扫描；MiniCANFD 枚举还要求本进程关闭同一厂商库的连接。不要强制终止他人的进程；系统或其他应用占用需由其所有者释放。不提供运行中重扫入口。

## MiniCANFD 通道选择

未配置全局 `channels` 或 `minicanfd.linux_channels` 时，Linux 自动探测通道 0；
仅在没有任何身份候选且成功释放探测资源后，才尝试通道 1；通道 0 非 FD 时直接检查 1。
通道 0 有任意身份候选即停止回退。显式指定通道会关闭此自动回退。
需要固定布局时填写已确认的 `linux_channels`，不要从设备数量推测通道。
Windows 用 DLL devNum 作为 device_index，channel_index 为 0，不填写 Linux 布局。
完整规则见[连接说明](manual_connection.md#minicanfd)。

## `unsupported_protocol` 或 FD 配方错误

核对适配器是否实际支持 FD、设备需要经典 CAN 还是 FD，以及时钟/位时序/数据速率是否匹配。PCAN classic 模板不能替代 FD 模板；SLCAN USB 识别不证明固件支持 FD，需已确认的 CANable 2.0 FD 固件。不要通过强行添加 `can_fd` 绕过 SDK 能力拒绝。

## `scan_timeout`：扫描预算耗尽

检查前面的后端失败及配置范围；有已知接口/Node ID/请求 ID 时限定正确范围，需要时调整 `total_timeout_s`。它是协作式预算，厂商阻塞调用及清理可能延长总耗时，不能把超过预算直接解释成死锁，也不要遗弃仍执行的后台任务。发送/响应预算与运行期事务预算分开。

## 探测关闭或运行期 cleanup 失败

日志给出原失败的接口/协议和每次清理原因。探测资源未释放会阻止保存/启动；运行期 close 失败仍需确认连接状态。处理库、占用或设备错误后按 SDK/适配器要求释放资源，再启动新会话。不能因报错后进程退出就声称厂商资源已释放。

## `identity_mismatch` 或保存角色匹配失败

激活/恢复的身份不符会拒绝控制。检查 node/namespace、接口、request/response ID、L30 Node ID 和原始 cause；文件匹配失败还显示保存的 `match` 条件。核对是否换手、换线、升级固件或编辑了选择条件，有序 cleanup 后重新发现并确认角色；不要删除身份条件来让错误设备通过。新生成文件使用新路径，保留原配置供核对。

模板中没有序列号的绑定只能提供型号/侧别/接口/端点约束，不能保证永久物理身份；生产部署优先生成现场文件。实机仍需独立验收。

[返回总览](getting_started.md) · [English](../discovery_troubleshooting.md)
