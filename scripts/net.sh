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
# Subnet cố định: heal cần nối lại đúng IP cũ (docker chỉ cho --ip khi mạng có subnet tự đặt).
# Vòng 5: container của 3 node có IP cố định trong 10.210.0.0/25 (infra/compose.local.yml, WAN_IP_PREFIX);
# IP động chỉ cấp trong DYNAMIC, nên không container nào lấy mất IP mà heal nối lại.
SUBNET=10.210.0.0/24
DYNAMIC=10.210.0.128/25

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
  ports="" ips=""
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

    # 3a. Kênh trực tiếp (vòng 3): bản sao gossip với bản sao khác qua REPLICA_URLS; chi nhánh tự báo địa chỉ
    #     POS (BRANCH_URL) trong heartbeat; tên node bị cut báo lỗi sau ~1 giây thay vì ~8 giây
    echo "$cfg" | grep -q "^replica_api  *REPLICA_URLS: " || bad "node $n: replica_api thiếu REPLICA_URLS (gossip)"
    echo "$cfg" | grep -q "^branch_api  *BRANCH_URL: http://branch-$n:8000\$" ||
      bad "node $n: branch_api phải có BRANCH_URL=http://branch-$n:8000"
    echo "$cfg" | grep -q "^replica_api  *- timeout:1\$" || bad "node $n: replica_api thiếu dns_opt timeout:1"

    # 3b. Mỗi node một broker (vòng 2): alias riêng trên default và wan, mã broker = BRANCH_ID,
    #     không publish cổng ra host (3 broker cùng máy sẽ đụng cổng 19092, 33145)
    c=$(echo "$cfg" | grep -ic "^redpanda .*- redpanda-$n\$" || true)
    [ "$c" -ge 2 ] || bad "node $n: redpanda thiếu alias redpanda-$n trên default và wan"
    id=$(sed -n 's/^BRANCH_ID=//p' "$env" | tr -d '\r')
    echo "$cfg" | grep -q "^redpanda .*--node-id=$id\$" || bad "node $n: redpanda phải có --node-id=$id (BRANCH_ID)"
    echo "$cfg" | grep -q '^redpanda .*published:' && bad "node $n: redpanda không được publish cổng ra host khi chạy một máy"
    grep -q "^BROKER_HOST=redpanda-$n\$" "$env" || bad "$env: BROKER_HOST phải là redpanda-$n"

    # 3c. Cổng vào (vòng 5): nginx ở MỌI node, nối minigo-wan, đủ địa chỉ host:port của 3 node;
    #     GATEWAYS có cổng vào của chính node này (trình duyệt cùng máy: http://localhost[:NGINX_PORT])
    echo "$cfg" | grep -q '^nginx  *wan:' || bad "node $n: nginx chưa chạy hoặc chưa nối vào minigo-wan (vòng 5: nginx ở mọi node)"
    for x in a b c; do
      X=$(echo "$x" | tr a-z A-Z)
      echo "$cfg" | grep -iq "^nginx  *REPLICA_$X: replica-$x:8000\$" || bad "node $n: nginx REPLICA_$X phải là replica-$x:8000"
      echo "$cfg" | grep -iq "^nginx  *BRANCH_$X: branch-$x:8000\$" || bad "node $n: nginx BRANCH_$X phải là branch-$x:8000"
    done
    own_gate "$env" localhost

    # 3d. IP cố định trên minigo-wan (vòng 5): mọi service nối wan có ipv4_address trong vùng tĩnh 10.210.0.2–127.
    #     Vùng động là 10.210.0.128/25 (net.sh up), nên không container nào lấy mất IP mà heal nối lại.
    for svc in $(echo "$cfg" | awk '$2 == "wan:" { print $1 }' | sort -u); do
      ip=$(echo "$cfg" | awk -v s="$svc" '$1 == s && $2 == "ipv4_address:" { gsub(/"/, "", $3); print $3 }')
      case "$ip" in
        10.210.0.*) o=${ip##*.}; [ "$o" -ge 2 ] && [ "$o" -le 127 ] || bad "node $n: $svc có IP $ip ngoài vùng tĩnh 10.210.0.2–127" ;;
        *) bad "node $n: $svc nối minigo-wan mà không có ipv4_address cố định trong 10.210.0.0/25 (có: '$ip')" ;;
      esac
      ips="$ips $ip"
    done
  done

  # 4. Node a: console, topic-init ở minigo-wan (gọi broker node khác)
  if [ -f infra/env/local-a.env ] && [ -f infra/compose.local.yml ] && raw=$(compose a config); then
    cfg=$(echo "$raw" | flat)
    for svc in console topic-init; do
      echo "$cfg" | grep -q "^$svc  *wan:" || bad "node a: $svc chưa nối vào minigo-wan (cần gọi broker node khác)"
    done
  fi
  dupip=$(echo $ips | tr ' ' '\n' | sort | uniq -d)
  [ -z "$dupip" ] || bad "IP cố định trùng giữa các container trên minigo-wan: $dupip"

  # 5. Template nginx dùng đủ 6 địa chỉ, không còn ghép ${IP_B}:cổng
  t=infra/nginx/default.conf.template
  for v in REPLICA_A REPLICA_B REPLICA_C BRANCH_A BRANCH_B BRANCH_C; do
    grep -v '^ *#' "$t" | grep -q "\${$v}" || bad "$t chưa dùng \${$v}"
  done
  grep -q 'IP_B\|IP_C' "$t" && bad "$t còn dùng IP_B/IP_C"
  # 5a. Vòng 5: phân giải tên động (nginx khởi động được khi node khác chưa chạy), CORS để trang chuyển cổng vào,
  #     danh sách cổng vào cho trình duyệt
  for p in 'resolver 127.0.0.11' 'Access-Control-Allow-Origin' '/lb/gateways.json' '${GATEWAYS}'; do
    grep -v '^ *#' "$t" | grep -qF -- "$p" || bad "$t thiếu '$p' (vòng 5)"
  done
  grep -v '^ *#' "$t" | grep -oE 'server \$\{[A-Z_]+\}[^;]*;' | grep -vq ' resolve' &&
    bad "$t: mọi 'server \${...}' trong upstream phải có 'resolve' (nginx không chết khi node khác chưa chạy)"
  grep -v '^ *#' "$t" | grep -q 'proxy_pass http://\${' &&
    bad "$t: proxy_pass phải trỏ vào upstream (có resolve), không trỏ thẳng \${REPLICA_X} (phân giải một lần lúc khởi động)"

  dup=$(echo $ports | tr ' ' '\n' | sort | uniq -d)
  [ -z "$dup" ] || bad "cổng host trùng giữa các node: $dup"

  # 6. Cụm broker, cả chế độ một máy (local-*) lẫn máy thật (may-*)
  cluster local
  cluster may

  [ $fail -eq 0 ] && echo "ĐẠT: cấu hình 3 node trên một máy, cụm 3 broker, cổng vào ở mọi node" || exit 1
}

# Cổng vào của chính node trong file env $1, nhìn từ trình duyệt ($2: localhost hoặc IP overlay), phải có trong GATEWAYS
own_gate() {
  port=$(sed -n 's/^NGINX_PORT=//p' "$1" | tr -d '\r')
  if [ -z "$port" ] || [ "$port" = 80 ]; then gw="http://$2"; else gw="http://$2:$port"; fi
  case ",$(sed -n 's/^GATEWAYS=//p' "$1" | tr -d '\r')," in
    *,"$gw",*) ;;
    *) bad "$1: GATEWAYS phải có cổng vào của chính node này ($gw)" ;;
  esac
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
    # Máy thật: BRANCH_URL là IP overlay của chính máy (cùng BROKER_HOST), cổng POS 8001 (vòng 3)
    [ "$1" != may ] || [ "$(val BRANCH_URL)" = "http://$host:8001" ] ||
      bad "$env: BRANCH_URL phải là http://$host:8001 (IP overlay của chính máy này, cổng POS)"
    # Vòng 5: nginx ở mọi máy với cùng một khối địa chỉ; máy thật dùng IP overlay cho cả máy của chính nginx
    gws=$(val GATEWAYS)
    [ -n "$gws" ] || bad "$env: thiếu GATEWAYS (danh sách cổng vào cho trình duyệt)"
    addr=""
    for X in A B C; do addr="$addr $(val REPLICA_$X) $(val BRANCH_$X)"; done
    if [ "$1" = may ]; then
      own_gate "$env" "$host"
      i=0
      for X in A B C; do
        i=$((i + 1)); h=$(echo "$kh" | sed -n "${i}p")   # host thứ i của KAFKA_BROKERS (không dùng `cut`: trùng hàm cut ở dưới)
        [ "$(val REPLICA_$X)" = "$h:8000" ] && [ "$(val BRANCH_$X)" = "$h:8001" ] ||
          bad "$env: REPLICA_$X, BRANCH_$X phải là $h:8000, $h:8001 (IP overlay; nginx chạy ở mọi máy nên không dùng tên service)"
      done
      docker compose --env-file "$env" -f infra/compose.yml config --services 2>/dev/null | grep -qx nginx ||
        bad "$env: máy này không chạy nginx (vòng 5: cổng vào ở mọi máy)"
    fi
    [ -z "$ref" ] && ref="$kb|$seeds|$gws|$addr"
    [ "$kb|$seeds|$gws|$addr" = "$ref" ] ||
      bad "$env: KAFKA_BROKERS, BROKER_SEEDS, GATEWAYS, REPLICA_*, BRANCH_* phải giống nhau ở 3 file $1-*.env"
    own="$own $host"
  done
  [ -z "$(echo $own | tr ' ' '\n' | sort | uniq -d)" ] || bad "$1-*.env: BROKER_HOST trùng giữa các node"
}

up() {
  if docker network inspect $WAN >/dev/null 2>&1; then
    [ "$(docker network inspect -f '{{range .IPAM.Config}}{{.IPRange}}{{end}}' $WAN)" = "$DYNAMIC" ] || {
      echo "Mạng $WAN tạo từ bản trước vòng 5 (chưa tách vùng IP động $DYNAMIC)."
      echo "Nâng từ bản trước: chạy make local-reset một lần (xoá dữ liệu demo, dựng lại mạng và schema)."
      exit 1
    }
  else
    docker network create --subnet $SUBNET --ip-range $DYNAMIC $WAN
  fi
  # c, b rồi a như trước; nginx phân giải tên động nên thứ tự không còn bắt buộc
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

# Nối lại đúng IP cũ: broker cần, vì kết nối RPC nó mở trước lúc rút mạng gắn với IP cũ, IP đổi thì treo mãi
# (đo ở vòng 2). IP cũ chính là IP cố định trong compose.local.yml, nằm ngoài vùng IP động, nên không đụng ai.
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
