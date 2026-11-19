#!/bin/sh
# =====================================================================
# Mô phỏng 3 máy trên MỘT máy (docs/plan.md vòng 1). Mỗi "máy" là một
# compose project minigo-a/b/c; "mạng overlay" là docker network minigo-wan.
# Chạy từ gốc repo, qua make:
#   sh scripts/net.sh check     kiểm cấu hình 3 node (make config gọi)
#   sh scripts/net.sh up        make local-up: tạo minigo-wan, dựng node c, b rồi a
#   sh scripts/net.sh down [-v] make local-down / local-reset (-v xoá cả dữ liệu)
#   sh scripts/net.sh cut b     make cut N=b: "rút dây mạng" node b
#   sh scripts/net.sh heal b    make heal N=b: "cắm lại", đúng IP và alias cũ
# =====================================================================
set -e
NODES="a b c"
WAN=minigo-wan
# Subnet cố định: heal cần nối lại đúng IP cũ (docker chỉ cho --ip khi mạng có subnet tự đặt)
SUBNET=10.210.0.0/24

# docker compose của node $1 (a, b, c), phần còn lại là tham số cho compose
compose() {
  n=$1; shift
  docker compose -p "minigo-$n" --env-file "infra/env/local-$n.env" \
    -f infra/compose.yml -f infra/compose.local.yml "$@"
}

# Cấu hình đã ghép (stdin) -> mỗi dòng trong services: có tên service đứng đầu: "<service> <dòng>"
flat() {
  awk '
    /^services:/ { s = 1; next }
    /^[^ ]/      { s = 0 }
    s && /^  [a-z_-]+:$/ { svc = $1; sub(":", "", svc) }
    s { print svc " " $0 }'
}

check() {
  fail=0
  bad() { echo "KHÔNG ĐẠT: $*"; fail=1; }
  ports=""
  for n in $NODES; do
    N=$(echo "$n" | tr a-z A-Z)
    env="infra/env/local-$n.env"
    [ -f "$env" ] || { bad "thiếu $env"; continue; }
    [ -f infra/compose.local.yml ] || { bad "thiếu infra/compose.local.yml"; break; }
    raw=$(compose "$n" config) || { bad "node $n: docker compose config lỗi"; continue; }
    cfg=$(echo "$raw" | flat)

    # 1. Cổng host: gom của cả 3 node, kiểm trùng ở cuối
    ports="$ports $(echo "$cfg" | awk '$2 == "published:" { gsub(/"/, "", $3); print $3 }')"

    # 2. Alias riêng của node, có trên cả mạng của node (default) lẫn minigo-wan
    for pair in "branch_api branch" "replica_api replica"; do
      set -- $pair
      c=$(echo "$cfg" | grep -ic "^$1 .*- $2-$n\$" || true)
      [ "$c" -ge 2 ] || bad "node $n: $1 thiếu alias $2-$n trên default và wan"
    done
    for svc in branch_api replica_api relay sink; do
      echo "$cfg" | grep -q "^$svc  *wan:" || bad "node $n: $svc chưa nối vào minigo-wan"
    done

    # 3. Giữa các node không gọi bằng tên service (trên minigo-wan nó trỏ về cả ba node)
    grep -E '^(REPLICA_URLS|KAFKA_BROKERS)=' "$env" | grep -q '_api' &&
      bad "$env: REPLICA_URLS/KAFKA_BROKERS dùng tên service, phải dùng alias"
    for x in a b c; do
      X=$(echo "$x" | tr a-z A-Z)
      grep -qi "^REPLICA_URLS=.*$X=http://replica-$x:8000" "$env" ||
        bad "$env: REPLICA_URLS thiếu $X=http://replica-$x:8000"
    done

    # 3b. Mỗi node một broker (vòng 2): alias riêng trên default và wan, mã broker = BRANCH_ID,
    #     không publish cổng ra host (3 broker cùng máy sẽ đụng cổng 19092, 33145)
    c=$(echo "$cfg" | grep -ic "^redpanda .*- redpanda-$n\$" || true)
    [ "$c" -ge 2 ] || bad "node $n: redpanda thiếu alias redpanda-$n trên default và wan"
    id=$(sed -n 's/^BRANCH_ID=//p' "$env" | tr -d '\r')
    echo "$cfg" | grep -q "^redpanda .*--node-id=$id\$" || bad "node $n: redpanda phải có --node-id=$id (BRANCH_ID)"
    echo "$cfg" | grep -q '^redpanda .*published:' && bad "node $n: redpanda không được publish cổng ra host khi chạy một máy"
    grep -q "^BROKER_HOST=redpanda-$n\$" "$env" || bad "$env: BROKER_HOST phải là redpanda-$n"
  done

  # 4. Node a: nginx ở minigo-wan; nginx đủ địa chỉ host:port của 3 node
  if [ -f infra/env/local-a.env ] && [ -f infra/compose.local.yml ] && raw=$(compose a config); then
    cfg=$(echo "$raw" | flat)
    echo "$cfg" | grep -q '^nginx  *wan:' || bad "node a: nginx chưa nối vào minigo-wan"
    for svc in console topic-init; do
      echo "$cfg" | grep -q "^$svc  *wan:" || bad "node a: $svc chưa nối vào minigo-wan (cần gọi broker node khác)"
    done
    for x in a b c; do
      X=$(echo "$x" | tr a-z A-Z)
      echo "$cfg" | grep -iq "^nginx  *REPLICA_$X: replica-$x:8000\$" || bad "nginx: REPLICA_$X phải là replica-$x:8000"
      echo "$cfg" | grep -iq "^nginx  *BRANCH_$X: branch-$x:8000\$" || bad "nginx: BRANCH_$X phải là branch-$x:8000"
    done
  fi

  # 5. Template nginx dùng đủ 6 địa chỉ, không còn ghép ${IP_B}:cổng
  t=infra/nginx/default.conf.template
  for v in REPLICA_A REPLICA_B REPLICA_C BRANCH_A BRANCH_B BRANCH_C; do
    grep -v '^ *#' "$t" | grep -q "\${$v}" || bad "$t chưa dùng \${$v}"
  done
  grep -q 'IP_B\|IP_C' "$t" && bad "$t còn dùng IP_B/IP_C"

  dup=$(echo $ports | tr ' ' '\n' | sort | uniq -d)
  [ -z "$dup" ] || bad "cổng host trùng giữa các node: $dup"

  # 6. Cụm broker, cả chế độ một máy (local-*) lẫn máy thật (may-*)
  cluster local
  cluster may

  [ $fail -eq 0 ] && echo "ĐẠT: cấu hình 3 node trên một máy và cụm 3 broker" || exit 1
}

# Ba file env của một chế độ ($1 = local hoặc may): KAFKA_BROKERS và BROKER_SEEDS liệt kê đủ 3 broker,
# cùng host, giống nhau ở cả 3 file; BROKER_HOST mỗi node khác nhau và nằm trong danh sách đó.
cluster() {
  ref="" own=""
  for x in a b c; do
    env="infra/env/$1-$x.env"
    [ -f "$env" ] || { bad "thiếu $env"; continue; }
    val() { sed -n "s/^$1=//p" "$env" | tr -d '\r'; }
    grep -q '^IP_A=' "$env" && bad "$env: còn IP_A (đã thay bằng BROKER_HOST)"
    case ",$(val COMPOSE_PROFILES)," in *,broker,*) ;; *) bad "$env: COMPOSE_PROFILES thiếu broker" ;; esac
    kb=$(val KAFKA_BROKERS); seeds=$(val BROKER_SEEDS); host=$(val BROKER_HOST)
    kh=$(echo "$kb" | tr ',' '\n' | sed -n 's/:19092$//p')
    sh_=$(echo "$seeds" | tr ',' '\n' | sed -n 's/:33145$//p')
    [ "$(echo "$kb" | tr ',' '\n' | grep -c .)" -eq 3 ] && [ "$(echo "$kh" | grep -c .)" -eq 3 ] ||
      bad "$env: KAFKA_BROKERS phải có đủ 3 địa chỉ <host>:19092"
    [ "$(echo "$seeds" | tr ',' '\n' | grep -c .)" -eq 3 ] && [ "$kh" = "$sh_" ] ||
      bad "$env: BROKER_SEEDS phải là 3 địa chỉ <host>:33145, cùng host và thứ tự với KAFKA_BROKERS"
    [ -n "$host" ] && echo "$kh" | grep -qx "$host" || bad "$env: BROKER_HOST ($host) không có trong KAFKA_BROKERS"
    [ -z "$ref" ] && ref="$kb|$seeds"
    [ "$kb|$seeds" = "$ref" ] || bad "$env: KAFKA_BROKERS, BROKER_SEEDS phải giống nhau ở 3 file $1-*.env"
    own="$own $host"
  done
  [ -z "$(echo $own | tr ' ' '\n' | sort | uniq -d)" ] || bad "$1-*.env: BROKER_HOST trùng giữa các node"
}

up() {
  docker network inspect $WAN >/dev/null 2>&1 || docker network create --subnet $SUBNET $WAN
  # c, b trước a: nginx ở node a phân giải replica-b, branch-c... MỘT lần lúc khởi động
  for n in c b a; do compose $n up -d --build; done
}

down() {
  for n in a b c; do compose $n down "$@"; done
  rm -f .cut-a .cut-b .cut-c
  docker network rm $WAN >/dev/null 2>&1 || true
}

node() {
  case "$1" in a|b|c) ;; *) echo "Chọn node: N=a, N=b hoặc N=c"; exit 1 ;; esac
}

# Gỡ mọi container của node khỏi minigo-wan. Node vẫn chạy đủ bên trong (CSDL, POS, bản sao),
# chỉ mất liên lạc với node khác, như rút dây mạng. Ghi lại IP và alias vào .cut-<node> cho heal.
cut() {
  node "$1"; f=".cut-$1"
  [ ! -f "$f" ] || { echo "Node $1 đang bị rút mạng rồi (có $f). Cắm lại: make heal N=$1"; exit 1; }
  ids=$(docker ps -q --filter "label=com.docker.compose.project=minigo-$1" --filter "network=$WAN")
  [ -n "$ids" ] || { echo "Node $1 không có container nào trên $WAN. Đã make local-up chưa?"; exit 1; }
  for c in $ids; do
    docker inspect -f "{{.Name}} {{with index .NetworkSettings.Networks \"$WAN\"}}{{.IPAddress}}{{range .Aliases}} {{.}}{{end}}{{end}}" "$c" |
      sed 's|^/||' >> "$f"
  done
  while read -r name ip aliases; do
    docker network disconnect $WAN "$name"
    echo "  rút: $name ($ip)"
  done < "$f"
  echo "Đã rút mạng node $1. Cắm lại: make heal N=$1"
}

# Nối lại đúng IP cũ: nginx ở node a nhớ IP từ lúc khởi động, IP đổi thì nó gửi nhầm container.
# Broker cũng cần: kết nối RPC nó mở trước lúc rút mạng gắn với IP cũ, IP đổi thì treo mãi (đo ở vòng 2).
# shortcut: IP ghim cứng không được giữ chỗ khi container dừng; container khác khởi động lại có thể lấy mất,
# bật lại báo "Address already in use" -> make local-reset.
heal() {
  node "$1"; f=".cut-$1"
  [ -f "$f" ] || { echo "Node $1 không bị rút mạng (không có $f)"; exit 1; }
  while read -r name ip aliases; do
    args=""
    for a in $aliases; do args="$args --alias $a"; done
    docker network connect --ip "$ip" $args $WAN "$name"
    echo "  cắm: $name ($ip)"
  done < "$f"
  rm "$f"
  echo "Đã cắm lại mạng node $1"
}

cmd=$1; [ $# -gt 0 ] && shift
case "$cmd" in
  check) check ;;
  up) up ;;
  down) down "$@" ;;
  cut) cut "$1" ;;
  heal) heal "$1" ;;
  *) echo "Dùng: sh scripts/net.sh check | up | down [-v] | cut <a|b|c> | heal <a|b|c>"; exit 1 ;;
esac
