#!/bin/sh
# =====================================================================
# K10a, K10b (vòng 7, PT-12): bằng chứng "không mất lượt bán nào đã báo thành công" và số đo độ trễ sync/async.
#   sh scripts/k10.sh sell <node> <giây>   bán liên tục ở POS của node (một máy: a 8001, b 8011, c 8021), mỗi lượt
#                                          một request_id mới; ghi "request_id mã_hàng mã_HTTP elapsed_ms giờ" vào
#                                          .k10-<node>.log (không commit); cuối cùng in số lượt theo mã HTTP, p50/p95
#   sh scripts/k10.sh verify <node>        đối chiếu log với stock_movement trên primary HIỆN TẠI (sau promote):
#                                          báo thành công mà thiếu (phải 0 ở chế độ đồng bộ), báo lỗi mà đã ghi; rồi
#                                          gửi lại mọi lượt báo lỗi với cùng request_id (như POS) và đếm `replayed`
# Lượt báo lỗi (503 db_unavailable, 000 = quá 5 giây / mất kết nối) là "chưa rõ": POS giữ request_id và gửi lại.
# =====================================================================
set -e
port() { case "$1" in a) echo 8001 ;; b) echo 8011 ;; c) echo 8021 ;; *) echo "Chọn node a, b hoặc c" >&2; exit 1 ;; esac; }

# POST một lượt bán 1 cái; in "mã_HTTP elapsed_ms replayed" (000 khi không có trả lời trong 5 giây)
sale() {
  out=$(curl -s -m 5 -w ' %{http_code}' -H 'Content-Type: application/json' \
    -d "{\"product_id\":$3,\"qty\":1,\"request_id\":\"$2\"}" "http://localhost:$1/api/sale" || true)
  code=${out##* }
  ms=$(echo "$out" | sed -n 's/.*"elapsed_ms":\([0-9.]*\).*/\1/p')
  rep=$(echo "$out" | grep -q '"replayed":true' && echo replayed || true)
  echo "${code:-000} ${ms:--} $rep"
}

sell() {
  p=$(port "$1"); log=".k10-$1.log"; end=$(($(date +%s) + ${2:-30})); i=0
  : > "$log"
  echo "Bán liên tục ở localhost:$p trong ${2:-30} giây, ghi $log"
  while [ "$(date +%s)" -lt "$end" ]; do
    i=$((i + 1)); rid="k10-$1-$(date +%s)-$i"; pid=$((i % 20 + 1))
    r=$(sale "$p" "$rid" "$pid")
    echo "$rid $pid $r $(date +%T)" | awk '{ print $1, $2, $3, $4, $NF }' >> "$log"
    sleep 0.2
  done
  summary "$log"
}

summary() {
  echo "Số lượt theo mã HTTP:"; awk '{ print "  " $3 }' "$1" | sort | uniq -c
  awk '$3 == 200 { print $4 }' "$1" | sort -n | awk '{ v[NR] = $1 } END {
    if (!NR) exit
    p50 = int(NR * 0.5) + 1; if (p50 > NR) p50 = NR
    p95 = int(NR * 0.95) + 1; if (p95 > NR) p95 = NR
    printf "elapsed_ms lượt thành công: n=%d p50=%s p95=%s max=%s\n", NR, v[p50], v[p95], v[NR] }'
}

verify() {
  p=$(port "$1"); log=".k10-$1.log"
  [ -s "$log" ] || { echo "Chưa có $log: chạy sell trước"; exit 1; }
  db=$(sh scripts/db.sh primary "$1")
  have=$(docker exec "$db" psql -U app -d kho -tAX -c "SELECT request_id FROM stock_movement WHERE request_id LIKE 'k10-$1-%'")
  ok=$(awk '$3 == 200 { print $1 }' "$log")
  bad=$(awk '$3 != 200 { print $1 }' "$log")
  n_ok=$(echo "$ok" | grep -c . || true)
  missing=$(echo "$ok" | grep . | grep -vxF "$(echo "$have" | grep . || echo '#')" || true)
  n_missing=$(echo "$missing" | grep -c . || true)
  n_bad=$(echo "$bad" | grep -c . || true)
  bad_in=$(echo "$bad" | grep . | grep -cxF "$(echo "$have" | grep . || echo '#')" || true)
  echo "Primary hiện tại: $db"
  echo "Báo thành công (200): $n_ok; có trong stock_movement: $((n_ok - n_missing)); THIẾU: $n_missing"
  [ "$n_missing" -eq 0 ] || echo "$missing" | sed 's/^/  thiếu: /'
  echo "Báo lỗi / không trả lời: $n_bad; trong đó đã ghi (COMMIT xong nhưng mất trả lời): $bad_in"
  if [ "$n_bad" -gt 0 ]; then
    echo "Gửi lại các lượt báo lỗi với cùng request_id (như POS):"
    awk '$3 != 200 { print $1, $2 }' "$log" | while read -r rid pid; do sale "$p" "$rid" "$pid"; done |
      awk '{ k = $1 ($3 == "replayed" ? " replayed (đã có, không trừ thêm)" : ($1 == 200 ? " ghi mới" : " lỗi")); c[k]++ }
           END { for (k in c) print "  " c[k] " lượt: " k }'
    dup=$(docker exec "$db" psql -U app -d kho -tAX -c \
      "SELECT count(*) - count(DISTINCT request_id) FROM stock_movement WHERE request_id LIKE 'k10-$1-%'")
    echo "Dòng sổ cái trùng request_id: $dup"
  fi
  if [ "$n_missing" -eq 0 ]; then echo "ĐẠT: không mất lượt bán nào đã báo thành công (PT-12)"
  else echo "KHÔNG ĐẠT: mất $n_missing lượt đã báo thành công (đúng kỳ vọng khi async: RPO > 0; sai nếu đang sync)"; fi
}

cmd=$1; [ $# -gt 0 ] && shift
case "$cmd" in
  sell) sell "$1" "$2" ;;
  verify) verify "$1" ;;
  *) echo "Dùng: sh scripts/k10.sh sell <node> <giây> | verify <node>"; exit 1 ;;
esac
