# remote

这个仓库当前主要包含 `teleop_bridge` ROS 2 Humble 软件包，用来把 Steam Deck
遥控、串口控制链路和网口画面透传拆开管理。

- 网口: 只负责桌面画面/远程桌面
- 串口: 只负责 100Hz 摇杆控制和机器人反馈

这样做的目标是把“高带宽画面”和“低时延控制”解耦。后续无论视频换成
Moonlight、Sunshine、GStreamer 还是自定义桌面推流，都不会影响 ROS 2 控制链路。

## 基础环境配置

推荐环境：

- Ubuntu 22.04
- ROS 2 Humble
- Python 3
- 有线网口，用于视频/桌面透传
- USB 串口设备，例如 `/dev/ttyUSB0`

### 1. 配置 ROS 2 apt 源

如果机器还没有安装 ROS 2 Humble，先配置 Ubuntu locale 和 ROS 2 软件源：

```bash
sudo apt update
sudo apt install -y locales software-properties-common curl gnupg lsb-release
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

sudo add-apt-repository universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
```

### 2. 安装 ROS 2 和常用工具

```bash
sudo apt update
sudo apt install -y \
  ros-humble-ros-base \
  ros-dev-tools \
  python3-colcon-common-extensions
```

让新终端自动加载 ROS 2 环境：

```bash
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
source /opt/ros/humble/setup.bash
```

如果你使用 zsh：

```bash
echo "source /opt/ros/humble/setup.zsh" >> ~/.zshrc
source /opt/ros/humble/setup.zsh
```

### 3. 安装本仓库运行依赖

```bash
sudo apt update
sudo apt install -y \
  ros-humble-rclpy \
  ros-humble-sensor-msgs \
  ros-humble-std-msgs \
  ros-humble-joy \
  ros-humble-launch \
  ros-humble-launch-ros \
  python3-serial \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav
```

串口权限建议把当前用户加入 `dialout` 组，执行后重新登录一次：

```bash
sudo usermod -aG dialout $USER
```

Steam Deck 如果手柄被系统的 lizard mode 占用，可以检查并临时关闭：

```bash
cat /sys/module/hid_steam/parameters/lizard_mode
sudo modprobe -r hid_steam
sudo modprobe hid_steam lizard_mode=0
```

## 构建

在仓库根目录执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select teleop_bridge
source install/setup.bash
```

## 当前实现

Steam Deck 端：

- 运行 `joy_node` 读取手柄
- `bridge_tx_node` 以 100Hz 缓存并发送最新摇杆值
- 传输 `Joy` 里的全部轴和全部按键
- 通过串口接收机器人回传反馈
- 发布 `/teleop_feedback`、`/teleop_feedback_flags`、`/teleop_link_connected`

机器人小电脑端：

- `bridge_rx_node` 以 100Hz 读取串口控制帧
- 以 100Hz 发布 `/joy_remote`
- 订阅本地反馈输入后，以 100Hz 通过串口回传到 Steam Deck
- 支持断链后继续发布全零 `Joy`，方便底盘安全停车
- 可选通过 `ros2 launch` 顺便启动以太网桌面推流

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

控制和视频一起启动时，机器人小电脑端：

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

```bash
ros2 launch teleop_bridge robot_bringup.launch.py \
  enable_control_link:=false \
  enable_video_stream:=true \
  video_target_ip:=192.168.1.10 \
  video_port:=5600
```

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
- `teleop: debug deck topics`: 并行查看 Steam Deck 侧 topic
- `teleop: debug robot topics`: 并行查看机器人侧 topic

如果你的串口设备不是 `/dev/ttyUSB0`，或接收端 IP 不是 `192.168.1.10`，
请直接修改 `.vscode/tasks.json` 中对应 launch 参数。

## Topic 调试

```bash
ros2 topic echo /joy
ros2 topic echo /joy_remote
ros2 topic echo /teleop_link_connected
ros2 topic echo /teleop_feedback
ros2 topic echo /teleop_feedback_flags
ros2 topic echo /teleop_feedback_in
ros2 topic echo /teleop_feedback_flags_in
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

## 串口协议简述

- 固定帧头: `0x55 0xAA`
- 协议版本: `2`
- 帧类型 `1`: 控制帧
- 帧类型 `2`: 反馈帧
- 轴值会从 `[-1.0, 1.0]` 压缩为 `int16`
- 当前上限: 轴最多 `64`，按键最多 `255`，反馈浮点值最多 `32`

反馈通道可以回传电池电压、速度、电机温度、模式状态位等机器人状态。

更完整的软件包说明仍保留在 [teleop_bridge/README.md](teleop_bridge/README.md)。
