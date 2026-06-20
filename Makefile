# 常用命令封装
.PHONY: up down logs ps migrate test backup restore e2e

up:            ## 一键起栈
	docker compose up -d --build

down:          ## 停栈
	docker compose down

logs:          ## 跟踪后端日志
	docker compose logs -f backend

ps:            ## 查看服务状态
	docker compose ps

migrate:       ## 在 backend 容器内执行迁移
	docker compose exec backend alembic upgrade head

test:          ## 后端单元测试
	cd backend && pytest

backup:        ## 数据库备份（pg_dump -Fc，含校验与保留清理）
	bash scripts/backup.sh

restore:       ## 数据库恢复：make restore FILE=backups/xxx.dump
	bash scripts/restore.sh $(FILE)

e2e:           ## 端到端联调冒烟（对 ems_mock）
	bash scripts/e2e_smoke.sh
