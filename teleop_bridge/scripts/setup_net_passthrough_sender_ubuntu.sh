#!/usr/bin/env bash
set -euo pipefail

ROLE="sender"
TARGET_IP=""
PORT="5600"
IFACE=""
STATIC_CIDR=""
GATEWAY=""
INSTALL_DEPS=0
OPEN_FIREWALL=0

usage() {
  cat <<'EOF'
Usage:
  setup_net_passthrough_sender_ubuntu.sh --target-ip <receiver_ip> [options]

Options:
  --target-ip IP       接收端/Steam Deck 的 IP，必填。
  --port PORT          UDP 目标端口，默认 5600。
  --interface IFACE    指定网卡名，例如 enp3s0。默认只检查默认路由网卡。
  --set-ip CIDR        可选：用 nmcli 给指定网卡配置静态 IPv4，例如 192.168.1.20/24。
  --gateway IP         可选：静态 IPv4 网关；直连测试可不填。
  --install            安装 GStreamer、ROS launch 测试所需常见依赖。
  --open-firewall      如果 ufw 已启用，放行指定 UDP 端口。
  -h, --help           显示帮助。

Example:
  ./setup_net_passthrough_sender_ubuntu.sh --target-ip 192.168.1.10 --interface enp3s0 --install
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-ip) TARGET_IP="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --interface) IFACE="${2:-}"; shift 2 ;;
    --set-ip) STATIC_CIDR="${2:-}"; shift 2 ;;
    --gateway) GATEWAY="${2:-}"; shift 2 ;;
    --install) INSTALL_DEPS=1; shift ;;
    --open-firewall) OPEN_FIREWALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

[[ -n "$TARGET_IP" ]] || die "发送端必须指定 --target-ip。"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "--port 必须是数字。"

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  info "系统: ${PRETTY_NAME:-unknown}"
  [[ "${ID:-}" == "ubuntu" ]] || echo "[WARN] 该脚本按 Ubuntu 编写，当前 ID=${ID:-unknown}。"
else
  echo "[WARN] 无法读取 /etc/os-release。"
fi

if [[ "$INSTALL_DEPS" -eq 1 ]]; then
  info "安装发送端依赖。需要 sudo 权限。"
  sudo apt-get update
  sudo apt-get install -y \
    iproute2 iputils-ping net-tools ufw network-manager \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    ros-humble-launch ros-humble-launch-ros
fi

if [[ -z "$IFACE" ]]; then
  IFACE="$(ip route get "$TARGET_IP" 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}' || true)"
fi
[[ -n "$IFACE" ]] || die "无法自动判断网卡，请用 --interface 指定。"

info "使用网卡: $IFACE"
ip link show "$IFACE" >/dev/null 2>&1 || die "网卡不存在: $IFACE"

if [[ -n "$STATIC_CIDR" ]]; then
  need_cmd nmcli || die "配置静态 IP 需要 nmcli，请先安装 network-manager。"
  info "配置静态 IPv4: $IFACE -> $STATIC_CIDR"
  sudo nmcli con mod "$IFACE" ipv4.method manual ipv4.addresses "$STATIC_CIDR"
  if [[ -n "$GATEWAY" ]]; then
    sudo nmcli con mod "$IFACE" ipv4.gateway "$GATEWAY"
  else
    sudo nmcli con mod "$IFACE" -ipv4.gateway || true
  fi
  sudo nmcli con mod "$IFACE" ipv4.dns ""
  sudo nmcli con up "$IFACE"
fi

info "网卡地址:"
ip -brief addr show "$IFACE"

if ping -c 2 -W 1 "$TARGET_IP" >/dev/null 2>&1; then
  info "能 ping 通接收端: $TARGET_IP"
else
  echo "[WARN] ping 不通 $TARGET_IP。若设备禁 ICMP 可忽略，否则先检查 IP、网线、同网段和防火墙。"
fi

if [[ "$OPEN_FIREWALL" -eq 1 ]] && need_cmd ufw && sudo ufw status | grep -q "Status: active"; then
  info "ufw 已启用，发送端通常不需要入站端口；这里不修改规则。"
fi

missing=0
for element in ximagesrc videoconvert x264enc rtph264pay udpsink; do
  if gst-inspect-1.0 "$element" >/dev/null 2>&1; then
    info "GStreamer element OK: $element"
  else
    echo "[WARN] 缺少 GStreamer element: $element"
    missing=1
  fi
done

if [[ -z "${DISPLAY:-}" ]]; then
  echo "[WARN] 未设置 DISPLAY。当前 launch 使用 ximagesrc，需要在 X11 桌面会话内运行。Wayland 会话建议改用 ximagesrc 可见的 XWayland 或替换为对应采集源。"
else
  info "DISPLAY=${DISPLAY}"
fi

if [[ "$missing" -ne 0 ]]; then
  echo "[WARN] GStreamer 组件不完整。可重新运行本脚本并加 --install。"
fi

cat <<EOF

发送端单独测试网口透传 launch:
  ros2 launch teleop_bridge robot_bringup.launch.py \\
    enable_control_link:=false \\
    enable_video_stream:=true \\
    video_target_ip:=${TARGET_IP} \\
    video_port:=${PORT}

裸 GStreamer 发送测试:
  gst-launch-1.0 -e ximagesrc use-damage=0 show-pointer=true ! \\
    video/x-raw,framerate=30/1,width=1280,height=720 ! videoconvert ! \\
    x264enc tune=zerolatency speed-preset=ultrafast bitrate=4000 key-int-max=30 ! \\
    rtph264pay pt=96 config-interval=1 ! udpsink host=${TARGET_IP} port=${PORT} sync=false async=false
EOF
