# teleop_bridge

`teleop_bridge` 是一个面向 ROS 2 Humble 的 Python 软件包，按如下方式拆分遥控链路：

- 网口: 只负责桌面画面/远程桌面
- 串口: 只负责 100Hz 摇杆控制和机器人反馈

这样做的目标是把“高带宽画面”和“低时延控制”彻底解耦，后续无论你把视频换成
Moonlight、Sunshine、GStreamer 还是自定义桌面推流，都不会影响 ROS 2 控制链路。

```bash
cat /sys/module/hid_steam/parameters/lizard_mode
```
```bash
sudo modprobe -r hid_steam
sudo modprobe hid_steam lizard_mode=0
```

## 当前实现

Steam Deck 端：

- 运行 `joy_node` 读取手柄
- `bridge_tx_node` 以 100Hz 缓存并发送最新摇杆值
- 当前会传输 `Joy` 里的全部轴和全部按键
- 同时通过串口接收机器人回传的反馈值
- 把反馈发布为 ROS 2 topic:
  - `/teleop_feedback` (`std_msgs/msg/Float32MultiArray`)
  - `/teleop_feedback_flags` (`std_msgs/msg/UInt16`)
  - `/teleop_link_connected` (`std_msgs/msg/Bool`)

机器人小电脑端：

- `bridge_rx_node` 以 100Hz 读取串口控制帧
- 以 100Hz 发布 `/joy_remote` (`sensor_msgs/msg/Joy`)
- 订阅本地反馈输入后，以 100Hz 通过串口回传到 Steam Deck
- 支持断链后继续发布全零 `Joy`，方便底盘安全停车
- 可选通过 `ros2 launch` 顺便启动以太网桌面推流

## 串口协议

### 帧头

- 固定帧头: `0x55 0xAA`
- 协议版本: `2`
- 帧类型:
  - `1`: 控制帧
  - `2`: 反馈帧

### 通用封装

- `header`: `2 bytes`
- `version`: `uint8`
- `frame_type`: `uint8`
- `seq`: `uint8`
- `payload_length`: `uint8`
- `payload`: `N bytes`
- `checksum`: `uint8`

### 控制帧负载

- `axis_count`: `uint8`
- `button_count`: `uint8`
- `button_bitmask`: `ceil(button_count / 8)` 字节
- `axes`: `int16 * N`

说明：

- 轴值在发送前会从 `[-1.0, 1.0]` 压缩为 `int16`
- 这样比直接发 `float32` 更适合串口 100Hz 场景
- 接收端会自动还原成 `sensor_msgs/msg/Joy`
- 当前协议上限:
  - 轴: 最多 `64`
  - 按键: 最多 `255`
  - 反馈浮点值: 最多 `32`

### 反馈帧负载

- `status_flags`: `uint16`
- `value_count`: `uint8`
- `values`: `float32 * N`

你可以把机器人状态例如：

- 电池电压
- 当前线速度
- 当前角速度
- 电机温度
- 模式状态位

都塞进这个反馈通道里。

## 依赖

- `rclpy`
- `sensor_msgs`
- `std_msgs`
- `joy`
- `pyserial`
- GStreamer: 用于网口视频透传测试和 launch 中的外部推流/接收进程

Ubuntu 22.04 + ROS 2 Humble 常用安装命令：

```bash
sudo apt update
sudo apt install -y \
  ros-humble-rclpy \
  ros-humble-sensor-msgs \
  ros-humble-std-msgs \
  ros-humble-joy \
  python3-serial \
  python3-colcon-common-extensions \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav
```

## 构建

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select teleop_bridge
source install/setup.bash
```

## 启动

Steam Deck 端：

```bash
ros2 launch teleop_bridge steamdeck_bringup.launch.py \
  serial_port:=/dev/ttyUSB0 \
  baudrate:=115200 \
  loop_hz:=100.0
```

机器人端：

```bash
ros2 launch teleop_bridge robot_bringup.launch.py \
  serial_port:=/dev/ttyUSB0 \
  baudrate:=115200 \
  loop_hz:=100.0
```

控制和视频一起启动：

机器人小电脑端：

```bash
ros2 launch teleop_bridge robot_bringup.launch.py \
  serial_port:=/dev/ttyUSB0 \
  baudrate:=115200 \
  loop_hz:=100.0 \
  enable_video_stream:=true \
  video_target_ip:=192.168.1.10 \
  video_port:=5600 \
  video_width:=1280 \
  video_height:=720 \
  video_fps:=30 \
  video_bitrate_kbps:=4000
```

Steam Deck 端：

```bash
ros2 launch teleop_bridge steamdeck_bringup.launch.py \
  serial_port:=/dev/ttyUSB0 \
  baudrate:=115200 \
  loop_hz:=100.0 \
  enable_video_stream:=true \
  video_port:=5600 \
  video_sink:=autovideosink
```

只测试网口视频透传，不启动手柄、串口控制桥：

机器人小电脑发送端：

```bash
ros2 launch teleop_bridge robot_bringup.launch.py \
  enable_control_link:=false \
  enable_video_stream:=true \
  video_target_ip:=192.168.1.10 \
  video_port:=5600
```

Steam Deck / Ubuntu 接收端：

```bash
ros2 launch teleop_bridge steamdeck_bringup.launch.py \
  enable_control_link:=false \
  enable_video_stream:=true \
  video_port:=5600 \
  video_sink:=autovideosink
```

## VS Code 开发任务

仓库根目录的 `.vscode/tasks.json` 已按当前 `teleop_bridge` 结构配置：

- `teleop: build`: 构建 `teleop_bridge`
- `teleop: run steamdeck`: 启动 Steam Deck 端，包含 `joy_node` 和 `bridge_tx_node`
- `teleop: run robot`: 启动机器人端 `bridge_rx_node`
- `teleop: run video receiver`: 只启动网口视频接收，不启动串口控制桥
- `teleop: run video sender`: 只启动网口视频发送，不启动串口控制桥
- `teleop: debug topics`: 并行查看 `/joy`、`/joy_remote`、`/teleop_link_connected`、`/teleop_feedback`

如果你的串口设备不是 `/dev/ttyUSB0`，或接收端 IP 不是 `192.168.1.10`，
请直接修改 `.vscode/tasks.json` 中对应 launch 参数。

## Topic 调试

查看 Steam Deck 本地手柄输入：

```bash
ros2 topic echo /joy
```

查看机器人端还原后的遥控输入：

```bash
ros2 topic echo /joy_remote
```

查看控制链路状态：

```bash
ros2 topic echo /teleop_link_connected
```

查看机器人回传反馈：

```bash
ros2 topic echo /teleop_feedback
ros2 topic echo /teleop_feedback_flags
```

## Ubuntu 网口透传测试脚本

新 Ubuntu 环境可以先用脚本检查网卡、IP、GStreamer 组件、防火墙和图形会话。
脚本默认只检查；加 `--install` 才会安装依赖，加 `--set-ip` 才会改静态 IP。

发送端，也就是运行桌面采集并向接收端推 UDP/RTP/H.264 的机器：

```bash
./teleop_bridge/scripts/setup_net_passthrough_sender_ubuntu.sh \
  --target-ip 192.168.1.10 \
  --interface enp3s0 \
  --install
```

接收端，也就是显示窗口并监听 UDP 端口的机器：

```bash
./teleop_bridge/scripts/setup_net_passthrough_receiver_ubuntu.sh \
  --interface enp3s0 \
  --set-ip 192.168.1.10/24 \
  --open-firewall \
  --install
```

直连网线测试时，两端可以分别配置同一网段静态 IP，例如接收端
`192.168.1.10/24`，发送端 `192.168.1.20/24`，不配置网关也可以。

## 机器人侧反馈输入示例

如果你想从机器人 ROS 节点回传 4 个浮点反馈值：

```python
from std_msgs.msg import Float32MultiArray

msg = Float32MultiArray()
msg.data = [24.1, 0.32, -0.08, 41.5]
publisher.publish(msg)
```

如果你想回传状态位：

```python
from std_msgs.msg import UInt16

msg = UInt16()
msg.data = 0b0000000000000011
publisher.publish(msg)
```

## 关于桌面画面

这个包里的视频部分不是 ROS topic 视频桥，而是借助 `ros2 launch` 顺便启动外部
GStreamer 进程。也就是说：

- 控制仍然走串口
- 视频仍然走纯以太网透传
- 只是统一由 launch 编排启动

当前默认视频方案：

- 机器人端: `ximagesrc + videoconvert + videoscale + videorate + x264enc + RTP/UDP`
- Steam Deck 端: `udpsrc + H264 解码 + 本地窗口显示`

更推荐的替代方案：

- Steam Deck + Moonlight
- 小电脑端 Sunshine
- 或者 GStreamer / WayVNC / RustDesk

原则是：

- 画面卡顿不能拖垮控制
- 控制串口抖动也不能影响桌面画面
- 如果你后面切 Sunshine/Moonlight，控制这套 ROS 2 + 串口桥不需要改
