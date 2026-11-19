# Lệnh thường dùng. Chạy từ gốc repo, trong Git Bash (Windows) hoặc shell Linux/macOS.
# Biến đọc từ .env ở gốc repo (chép từ infra/env/may-<x>.env); đổi file: make up ENV_FILE=...
ENV_FILE ?= .env
COMPOSE = docker compose --env-file $(ENV_FILE) -f infra/compose.yml
# make logs S=relay  (để trống = mọi service); make logs N=200
S ?=
N ?= 100

.PHONY: up down reset ps logs test config check

# Dựng và chạy mọi container của máy này (máy A thêm redpanda, console, nginx)
up:
	$(COMPOSE) up -d --build

# Dừng, giữ dữ liệu
down:
	$(COMPOSE) down

# Xóa cả dữ liệu rồi dựng lại từ đầu. Làm lại sạch thì chạy trên MỌI máy, máy A trước.
reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build

ps:
	@$(COMPOSE) ps -a

logs:
	@$(COMPOSE) logs --tail=$(N) $(S)

# pytest trong container, trên CSDL test riêng (infra/compose.test.yml). Một thư mục: make test T=tests/replica
T ?=
test:
	docker compose -f infra/compose.test.yml run --rm --build tests pytest $(T)

# File compose hợp lệ với env mẫu; không cần .env, không chạy container
config:
	docker compose --env-file infra/env/may-a.env -f infra/compose.yml config -q
	docker compose --env-file infra/env/may-b.env -f infra/compose.yml config -q
	docker compose -f infra/compose.test.yml config -q

# Chạy trước khi báo xong một vòng
check: config test
