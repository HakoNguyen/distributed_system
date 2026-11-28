#!/bin/sh
# =====================================================================
# Standby CSDL chi nhánh (vòng 7, PT-12; docs/db.md mục 2, docs/demo.md K10a–K10c). Chạy từ gốc repo, qua make:
#   sh scripts/db.sh status [node]            make db-status N=b: vai trò hai CSDL, sync/async, standby, độ trễ
#   sh scripts/db.sh sync-mode <node> <mode>   make sync-mode N=b MODE=sync|async (trên primary hiện tại)
#   sh scripts/db.sh promote [node]           make promote N=b: FENCE primary cũ, rồi nâng standby thành primary
#   sh scripts/db.sh rejoin [node]            make rejoin N=b: đưa CSDL đã bị fence về làm standby
#   sh scripts/db.sh backup [node]            make backup N=b: pg_dump primary hiện tại vào backups/
#   sh scripts/db.sh primary [node]           in tên container primary (scripts/k10.sh dùng)
# node: a, b, c khi chạy một máy (project minigo-<node>); bỏ trống trên máy thật (project minigo).
# Tên service không còn là vai trò: sau promote, branch_db_standby là primary. Script tự hỏi vai trò từng container.
# =====================================================================
set -e
export MSYS_NO_PATHCONV=1   # Git Bash trên Windows: không đổi /var/lib/... thành đường dẫn Windows khi gọi docker
IMAGE=postgres:16.16-alpine
DATA=/var/lib/postgresql/data
FENCE=minigo.fenced
SERVICES="branch_db branch_db_standby"

project() { if [ -n "$1" ]; then echo "minigo-$1"; else echo minigo; fi; }
running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
sql() { c=$1; shift; docker exec "$c" psql -U app -d kho -tAX "$@"; }
# Vai trò của container: primary, standby, down (không chạy / chưa nhận kết nối)
role() {
  running "$1" || { echo down; return; }
  case "$(sql "$1" -c 'SELECT pg_is_in_recovery()' 2>/dev/null)" in
    f) echo primary ;; t) echo standby ;; *) echo down ;;
  esac
}
fenced() { docker run --rm --volumes-from "$1" "$IMAGE" test -f "$DATA/$FENCE" 2>/dev/null; }
find_role() {   # $1 project, $2 vai trò cần tìm: in tên container, không có thì in rỗng
  for s in $SERVICES; do c="$1-$s-1"; [ "$(role "$c")" = "$2" ] && { echo "$c"; return; }; done
  true
}
need_primary() {
  p=$(find_role "$1" primary)
  [ -n "$p" ] || { echo "Không có CSDL chi nhánh nào đang là primary ở $1 (make db-status)." >&2; exit 1; }
  echo "$p"
}

status() {
  P=$(project "$1")
  for s in $SERVICES; do
    c="$P-$s-1"
    if ! docker inspect "$c" >/dev/null 2>&1; then echo "$s: không có container $c"; continue; fi
    r=$(role "$c"); extra=""
    [ "$r" = down ] && fenced "$c" && extra=" (ĐÃ BỊ FENCE: make rejoin)"
    if [ "$r" = primary ]; then
      names=$(sql "$c" -c "SHOW synchronous_standby_names")
      mode=async; [ -n "$(echo "$names" | tr -d ' ')" ] && mode=sync
      tl=$(sql "$c" -c "SELECT timeline_id FROM pg_control_checkpoint()")
      extra=" chế độ $mode, timeline $tl"
      rep=$(sql "$c" -c "SELECT string_agg(application_name || ' ' || client_addr || ' ' || state || ' ' || sync_state
                                        || ' trễ ' || pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) || ' byte', '; ')
                         FROM pg_stat_replication")
      extra="$extra; standby: ${rep:-KHÔNG CÓ}"
    fi
    echo "$s ($c): $r$extra"
  done
}

sync_mode() {
  case "$2" in sync) v='*' ;; async) v='' ;; *) echo "Chọn MODE=sync hoặc MODE=async"; exit 1 ;; esac
  p=$(need_primary "$(project "$1")")
  sql "$p" -c "ALTER SYSTEM SET synchronous_standby_names = '$v'" -c "SELECT pg_reload_conf()" >/dev/null
  echo "$p: chế độ $2 (synchronous_standby_names = '$v', synchronous_commit = $(sql "$p" -c 'SHOW synchronous_commit'))"
  [ "$2" = sync ] && [ -z "$(sql "$p" -c "SELECT 1 FROM pg_stat_replication WHERE state = 'streaming'")" ] &&
    echo "CẢNH BÁO: chưa có standby streaming, lượt bán sẽ TREO tới khi có standby hoặc make sync-mode MODE=async"
  true
}

# Fence TRƯỚC, promote SAU: primary cũ không bao giờ được chạy lại làm primary (split-brain, K10c)
promote() {
  P=$(project "$1")
  new=$(find_role "$P" standby)
  [ -n "$new" ] || { echo "Không có standby nào đang chạy ở $P để promote (make db-status)."; exit 1; }
  for s in $SERVICES; do [ "$P-$s-1" != "$new" ] && old="$P-$s-1"; done
  echo "1/4 Fence primary cũ $old: tắt tự khởi động lại, giết container, ghi $FENCE vào volume"
  docker update --restart=no "$old" >/dev/null
  docker kill "$old" >/dev/null 2>&1 || true   # chạy được cả khi container đang pause
  docker run --rm --volumes-from "$old" "$IMAGE" sh -c "touch $DATA/$FENCE"
  echo "2/4 Nâng $new thành primary (pg_promote)"
  [ "$(sql "$new" -c 'SELECT pg_promote(true, 30)')" = t ] || { echo "pg_promote không xong trong 30 giây"; exit 1; }
  # Async: relay có thể đã gửi lên Redpanda các movement_id mà standby chưa nhận; nhảy sequence để không cấp lại số đó
  echo "3/4 Nhảy sequence movement_id thêm 1000 (không cấp lại số primary cũ có thể đã dùng)"
  sql "$new" -c "SELECT setval('stock_movement_movement_id_seq', (SELECT last_value FROM stock_movement_movement_id_seq) + 1000)" >/dev/null
  echo "4/4 Đặt bất đồng bộ trên primary mới (chưa có standby; để đồng bộ thì mọi lượt bán sẽ treo)"
  sql "$new" -c "ALTER SYSTEM SET synchronous_standby_names = ''" -c "SELECT pg_reload_conf()" >/dev/null
  echo "Xong: primary mới là $new, timeline $(sql "$new" -c 'SELECT timeline_id FROM pg_control_checkpoint()')."
  echo "branch_api, relay tự nối lại qua chuỗi nhiều host. Đưa $old về làm standby: make rejoin N=$1"
}

rejoin() {
  P=$(project "$1")
  p=$(need_primary "$P")
  for s in $SERVICES; do [ "$P-$s-1" != "$p" ] && old="$P-$s-1"; done
  [ "$(role "$old")" = down ] || { echo "$old đang chạy Postgres ($(role "$old")), không phải CSDL đã bị fence."; exit 1; }
  # Tắt tự khởi động lại và dừng hẳn TRƯỚC khi xoá dữ liệu: make local-up có thể đã tạo lại container (restart
  # unless-stopped, vòng khởi động lại vì fence); bật lên đúng lúc thư mục trống thì initdb thành một primary mới
  docker update --restart=no "$old" >/dev/null
  docker stop "$old" >/dev/null 2>&1 || true
  fenced "$old" || echo "Lưu ý: $old không có $FENCE (không qua make promote); vẫn dựng lại làm standby."
  host=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$p")
  net=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$p" | tr ' ' '\n' | grep '_default$')
  pw=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$p" | sed -n 's/^REPLICATION_PASSWORD=//p')
  echo "1/3 Xoá dữ liệu cũ của $old (các lượt chỉ có ở primary cũ, nếu có, mất ở đây: RPO của chế độ async)"
  echo "2/3 pg_basebackup từ $host (primary mới) qua mạng $net"
  docker run --rm --volumes-from "$old" --network "$net" -e PGPASSWORD="$pw" "$IMAGE" sh -c \
    "rm -rf $DATA/* && su-exec postgres pg_basebackup -h $host -U replicator -D $DATA -R -X stream -c fast"
  echo "3/3 Bật lại $old làm standby, trả restart: unless-stopped"
  docker update --restart=unless-stopped "$old" >/dev/null
  docker start "$old" >/dev/null
  i=0
  until [ -n "$(sql "$p" -c "SELECT 1 FROM pg_stat_replication WHERE state = 'streaming'")" ]; do
    i=$((i + 1)); [ $i -le 60 ] || { echo "Standby chưa streaming sau 60 giây: docker logs $old"; exit 1; }
    sleep 1
  done
  echo "Xong: $old là standby của $p (streaming). Chế độ hiện tại: async; đồng bộ: make sync-mode N=$1 MODE=sync"
}

backup() {
  p=$(need_primary "$(project "$1")")
  mkdir -p backups
  f="backups/${1:-minigo}-$(date +%Y%m%d-%H%M%S).dump"
  docker exec "$p" pg_dump -U app -d kho -Fc > "$f"
  echo "Đã sao lưu $p vào $f ($(wc -c < "$f") byte). Khôi phục: docker exec -i $p pg_restore -U app -d kho --clean < $f"
}

cmd=$1; [ $# -gt 0 ] && shift
case "$cmd" in
  status) status "$1" ;;
  sync-mode) sync_mode "$1" "$2" ;;
  promote) promote "$1" ;;
  rejoin) rejoin "$1" ;;
  backup) backup "$1" ;;
  primary) need_primary "$(project "$1")" ;;
  *) echo "Dùng: sh scripts/db.sh status|promote|rejoin|backup|primary [node] | sync-mode <node> sync|async"; exit 1 ;;
esac
