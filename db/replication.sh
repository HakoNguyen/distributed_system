#!/bin/sh
# Vòng 7 (PT-12): chạy MỘT lần lúc initdb của primary đầu tiên (branch_db), mount thành
# /docker-entrypoint-initdb.d/03-replication.sh. Tạo user replicator cho streaming replication và cho phép nó nối
# vào kênh replication. Standby chép cả role lẫn pg_hba.conf qua pg_basebackup, nên đổi vai trò (promote, rejoin)
# không phải cấu hình lại.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v pw="$REPLICATION_PASSWORD" <<'EOSQL'
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD :'pw';
EOSQL
# "all" trong cột database của pg_hba không gồm kết nối replication: phải ghi riêng
echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"
