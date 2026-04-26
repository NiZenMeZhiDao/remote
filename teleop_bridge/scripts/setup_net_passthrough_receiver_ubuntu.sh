#!/usr/bin/env bash
set -euo pipefail

PORT="5600"
IFACE=""
STATIC_CIDR=""
GATEWAY=""
INSTALL_DEPS=0
OPEN_FIREWALL=0
VIDEO_SINK="autovideosink"

usage() {
  cat <<'EOF'
Usage:
  setup_net_passthrough_receiver_ubuntu.sh [options]

Options:
  --port PORT          UDP 接收端口，默认 5600。
  --interface IFACE    指定网卡名，例如 enp3s0。
  --set-ip CIDR        可选：用 nmcli 给指定网卡配置静态 IPv4，例如 192.168.1.10/24。
  --gateway IP         可选：静态 IPv4 网关；直连测试可不填。
  --video-sink SINK    GStreamer 显示 sink，默认 autovideosink；Steam Deck 可试 glimagesink。
  --install            安装 GStreamer、ROS launch 测试所需常见依赖。
  --open-firewall      如果 ufw 已启用，放行指定 UDP 端口。
  -h, --help           显示帮助。

Example:
  ./setup_net_passthrough_receiver_ubuntu.sh --interface enp3s0 --set-ip 192.168.1.10/24 --install --open-firewall
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
    --port) PORT="${2:-}"; shift 2 ;;
    --interface) IFACE="${2:-}"; shift 2 ;;
    --set-ip) STATIC_CIDR="${2:-}"; shift 2 ;;
    --gateway) GATEWAY="${2:-}"; shift 2 ;;
    --video-sink) VIDEO_SINK="${2:-}"; shift 2 ;;
    --install) INSTALL_DEPS=1; shift ;;
    --open-firewall) OPEN_FIREWALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

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
  info "安装接收端依赖。需要 sudo 权限。"
  sudo apt-get update
  sudo apt-get install -y \
    iproute2 iputils-ping net-tools ufw network-manager \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    ros-humble-launch ros-humble-launch-ros
fi

if [[ -n "$IFACE" ]]; then
  ip link show "$IFACE" >/dev/null 2>&1 || die "网卡不存在: $IFACE"
else
  IFACE="$(ip route show default 2>/dev/null | awk '{print $5; exit}' || true)"
  [[ -n "$IFACE" ]] || IFACE="$(ip -brief link | awk '$1 != "lo" {print $1; exit}' || true)"
fi
[[ -n "$IFACE" ]] || die "无法自动判断网卡，请用 --interface 指定。"

info "使用网卡: $IFACE"

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

if [[ "$OPEN_FIREWALL" -eq 1 ]] && need_cmd ufw; then
  if sudo ufw status | grep -q "Status: active"; then
    info "ufw 已启用，放行 UDP/${PORT}。"
    sudo ufw allow "${PORT}/udp"
  else
    info "ufw 未启用，不需要放行端口。"
  fi
fi

missing=0
for element in udpsrc rtpjitterbuffer rtph264depay avdec_h264 videoconvert "$VIDEO_SINK"; do
  if gst-inspect-1.0 "$element" >/dev/null 2>&1; then
    info "GStreamer element OK: $element"
  else
    echo "[WARN] 缺少 GStreamer element: $element"
    missing=1
  fi
done

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "[WARN] 未检测到图形会话环境变量。接收端显示窗口需要桌面会话；无桌面时请改用 fakesink 或文件保存管线。"
else
  info "图形会话: DISPLAY=${DISPLAY:-unset}, WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset}"
fi

if need_cmd ss; then
  if ss -lun | awk '{print $5}' | grep -Eq "[:.]${PORT}$"; then
    echo "[WARN] 当前已有进程监听 UDP/${PORT}，启动接收端前请确认没有端口冲突。"
  else
    info "UDP/${PORT} 当前未被监听。"
  fi
fi

if [[ "$missing" -ne 0 ]]; then
  echo "[WARN] GStreamer 组件不完整。可重新运行本脚本并加 --install。"
fi

cat <<EOF

接收端单独测试网口透传 launch:
  ros2 launch teleop_bridge steamdeck_bringup.launch.py \\
    enable_control_link:=false \\
    enable_video_stream:=true \\
    video_port:=${PORT} \\
    video_sink:=${VIDEO_SINK}

裸 GStreamer 接收测试:
  gst-launch-1.0 -e udpsrc port=${PORT} \\
    caps=application/x-rtp,media=video,encoding-name=H264,payload=96 ! \\
    rtpjitterbuffer latency=10 drop-on-latency=true ! rtph264depay ! \\
    avdec_h264 ! videoconvert ! ${VIDEO_SINK} sync=false
EOF
