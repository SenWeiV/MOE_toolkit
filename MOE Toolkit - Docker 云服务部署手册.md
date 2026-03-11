# MOE Toolkit Docker 云服务部署手册

文档版本：v1.0  
更新时间：2026-03-08

## 1. 目标

本文档用于指导将 MOE Toolkit 云端服务部署到你的百度云服务器，部署方式固定为单机 Docker Compose。

服务器信息参考：

- `/Users/weisen/Documents/small-project/百度云服务器通用配置.md`

首版固定部署目标：

- 服务器：`${MOE_PUBLIC_HOST}`
- 系统：`Ubuntu 22.04`
- 部署路径：`/opt/moe-toolkit`
- 对外入口：`${MOE_PUBLIC_BASE_URL}`

## 2. 首版服务清单

| 服务名 | 说明 | 对外暴露 |
| --- | --- | --- |
| `moe-api` | FastAPI 网关 | `8080` |
| `moe-worker` | 任务消费与工具容器编排 | 否 |
| `cleanup-job` | 上传与产物清理任务 | 否 |

## 3. 端口与安全组

首版只开放以下端口：

| 端口 | 协议 | 用途 |
| --- | --- | --- |
| `22` | TCP | SSH |
| `8080` | TCP | MOE Cloud API |

禁止公网开放：

- `5432`
- `6379`
- 任意调试端口

## 4. 服务器目录结构

```text
/opt/moe-toolkit/
  data/
    admin/
    releases/
    runs/
    uploads/
  source/
    deploy/docker/compose.prod.yml
  .env.prod
```

## 5. 部署前准备

### 5.1 创建目录

```bash
mkdir -p /opt/moe-toolkit/source
mkdir -p /opt/moe-toolkit/data/admin
mkdir -p /opt/moe-toolkit/data/releases
mkdir -p /opt/moe-toolkit/data/runs
mkdir -p /opt/moe-toolkit/data/uploads
```

### 5.2 安装 Docker

首版要求服务器具备：

- Docker Engine
- Docker Compose Plugin

验证命令：

```bash
docker --version
docker compose version
```

## 6. 环境变量

`/opt/moe-toolkit/.env.prod` 固定至少包含：

```dotenv
MOE_ENV=beta
MOE_API_KEYS_RAW=<comma-separated-active-keys>
MOE_PUBLIC_BASE_URL=${MOE_PUBLIC_BASE_URL}
MOE_API_KEY_STORE_PATH=/srv/moe/admin/api_keys.json
MOE_ADMIN_USERNAME=operator
MOE_ADMIN_PASSWORD=<strong-password>
MOE_ADMIN_SESSION_SECRET=<long-random-secret>
```

说明：

- `MOE_ADMIN_*` 为空时，`/admin/login` 后台默认关闭
- `MOE_API_KEY_STORE_PATH` 用于云端后台发 key / 吊销 key 后的实时生效

## 7. Compose 设计

`compose.prod.yml` 固定包含以下能力：

- `moe-api`
  - 映射 `8080:8080`
  - 挂载 `/opt/moe-toolkit/data:/srv/moe`
  - 提供 `/beta`、`/install.sh`、`/admin/login`
- `moe-worker`
  - 不暴露端口
  - 挂载 `/opt/moe-toolkit/data:/srv/moe`
  - 挂载 `/var/run/docker.sock`
- `cleanup-job`
  - 周期清理过期文件

## 8. 首次部署流程

### 8.1 上传发布包

将项目上传到服务器，例如：

```bash
scp -r /path/to/project ${MOE_REMOTE_HOST}:/opt/moe-toolkit/releases/current
```

### 8.2 启动服务

```bash
cd /opt/moe-toolkit/source
docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml up -d --build
```

### 8.3 检查服务

```bash
cd /opt/moe-toolkit/source
docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml ps
curl ${MOE_PUBLIC_BASE_URL}/v1/service/health
curl -I ${MOE_PUBLIC_BASE_URL}/admin/login
```

## 9. 运维检查

### 9.1 日志

```bash
cd /opt/moe-toolkit/source
docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml logs -f moe-api
docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml logs -f moe-worker
docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml logs -f cleanup-job
```

### 9.2 容器状态

```bash
cd /opt/moe-toolkit/source
docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml ps
docker stats
```

### 9.3 数据目录

```bash
du -sh /opt/moe-toolkit/data/uploads
du -sh /opt/moe-toolkit/data/runs
du -sh /opt/moe-toolkit/data/admin
```

## 10. 备份

首版至少备份：

- `/opt/moe-toolkit/.env.prod`
- `/opt/moe-toolkit/data/admin/api_keys.json`
- `/opt/moe-toolkit/data/releases/`

不备份：

- 过期上传文件
- 已下载产物

## 11. 升级策略

升级顺序固定为：

1. 备份 `/opt/moe-toolkit/.env.prod` 和 `data/admin/api_keys.json`
2. 上传新 release
3. `docker compose --env-file /opt/moe-toolkit/.env.prod -f deploy/docker/compose.prod.yml up -d --build`
4. 检查健康接口
5. 检查 `moe-worker` 可正常消费任务

## 12. 首版运维红线

- 不要把 `5432` 和 `6379` 开到公网
- 不要把上传文件长期保留
- 不要直接在宿主机运行应用进程替代容器
- 不要在首版混入 Nginx、HTTPS、账号体系等非必须复杂度
