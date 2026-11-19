#!/bin/sh
# =====================================================================
# Giả lập mạng xấu NGAY TRONG CONTAINER, chỉ trên đường đi tới một IP
# (thường là máy A). Kết nối tới CSDL cục bộ không bị ảnh hưởng, nên
# quầy vẫn bán nhanh như thường.
#
# Dùng (chạy trên máy chi nhánh, trong thư mục gốc dự án):
#   docker compose exec relay      sh tre.sh on 300 100.64.0.1       # trễ 300 ms
#   docker compose exec relay      sh tre.sh on 300 100.64.0.1 20    # trễ 300 ms, mất 20% gói
#   docker compose exec relay      sh tre.sh off
#   (làm tương tự với branch_api để heartbeat/RTT cũng bị trễ)
# =====================================================================
set -e
DEV=eth0
case "$1" in
  on)
    MS=${2:?Thiếu số mili giây}
    IP=${3:?Thiếu IP đích}
    LOSS=${4:-0}
    tc qdisc del dev $DEV root 2>/dev/null || true
    # prio tạo 3 "làn"; gói bình thường đi làn 1-2, chỉ gói tới $IP bị lọc vào làn 3
    tc qdisc add dev $DEV root handle 1: prio
    tc qdisc add dev $DEV parent 1:3 handle 30: netem delay ${MS}ms loss ${LOSS}%
    tc filter add dev $DEV protocol ip parent 1:0 prio 3 u32 match ip dst $IP/32 flowid 1:3
    echo "Đã thêm trễ ${MS} ms, mất gói ${LOSS}%, cho gói tin đi tới $IP"
    ;;
  off)
    tc qdisc del dev $DEV root 2>/dev/null || true
    echo "Đã bỏ giả lập, mạng trở lại bình thường"
    ;;
  *)
    echo "Dùng: sh tre.sh on <ms> <ip> [phần trăm mất gói]   hoặc   sh tre.sh off"
    exit 1
    ;;
esac
