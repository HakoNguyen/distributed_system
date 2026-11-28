#!/bin/sh
# Vòng 7: lệnh khởi động của branch_db và branch_db_standby (infra/compose.yml), chạy với quyền root như entrypoint gốc.
#   1. Fencing: có file minigo.fenced (make promote ghi vào primary cũ) thì THOÁT, không chạy Postgres. Primary cũ sống
#      lại mà tự coi là primary thì chuỗi nhiều host của branch_api có thể nối nhầm vào nó (split-brain). Đưa nó quay
#      lại làm standby: make rejoin N=<node>.
#   2. Thư mục dữ liệu trống và có PG_PRIMARY_HOST (chỉ standby lần đầu): pg_basebackup -R từ primary (ghi
#      standby.signal và primary_conninfo), chờ tới khi primary trả lời.
#   3. Chạy Postgres như entrypoint gốc (thư mục trống mà không có PG_PRIMARY_HOST thì initdb và chạy db/*.sql).
#      wal_keep_size: giữ WAL cho standby bắt kịp sau khi dừng một lúc; không dùng replication slot để standby chết lâu
#      không làm đầy đĩa primary.
set -e
D=${PGDATA:-/var/lib/postgresql/data}

if [ -f "$D/minigo.fenced" ]; then
  echo "[pg-start] CSDL này đã bị FENCE (primary cũ, trước lần make promote). Không chạy Postgres để tránh hai primary."
  echo "[pg-start] Đưa về làm standby của primary mới: make rejoin N=<node> (xoá dữ liệu cũ của nó, pg_basebackup lại)."
  exit 1
fi

if [ -n "$PG_PRIMARY_HOST" ] && [ ! -s "$D/PG_VERSION" ]; then
  echo "[pg-start] Thư mục dữ liệu trống: chép từ primary $PG_PRIMARY_HOST (pg_basebackup), rồi chạy làm standby"
  mkdir -p "$D"
  chown postgres:postgres "$D"
  chmod 700 "$D"
  until PGPASSWORD="$REPLICATION_PASSWORD" su-exec postgres \
      pg_basebackup -h "$PG_PRIMARY_HOST" -U replicator -D "$D" -R -X stream -c fast; do
    echo "[pg-start] Chưa chép được từ $PG_PRIMARY_HOST, thử lại sau 3 giây"
    rm -rf "${D:?}"/*
    sleep 3
  done
fi

exec docker-entrypoint.sh postgres -c wal_keep_size=256MB "$@"
