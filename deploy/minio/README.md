# MinIO LAN 部署（192.168.2.44）

> 目标：为 AI 离职流程系统提供 S3 兼容对象存储（节点附件、签字 PDF、设备照片、合同导出等）。

## 访问入口

| 用途        | URL                            | 凭证                     |
| ----------- | ------------------------------ | ------------------------ |
| Web Console | `http://192.168.2.44:9001`     | admin / `laios1855`      |
| S3 API      | `http://192.168.2.44:9000`     | Access Key = root，或 ServiceAccount |

## 预置 buckets（与 PRD 集成约定）

| Bucket                     | 用途                                                 |
| -------------------------- | ---------------------------------------------------- |
| `offboarding-attachments`  | 节点 result_text 附带的图片 / PDF / Excel            |
| `offboarding-exports`      | 流程结束生成的离职证明 PDF、归档包                   |
| `offboarding-screenshots`  | 演示 / 测试场景下用于截图存档                       |

## 部署目录

服务器路径：`/home/laios/minio/`（WSL Ubuntu 内）

```
~/minio/
├── docker-compose.yml      # 与本目录同步
├── .env                    # 真实凭证（在服务器上，已 chmod 600）
└── data/                   # MinIO 持久化数据（不入 git）
```

## 部署步骤（已执行）

```bash
# 服务器侧
mkdir -p ~/minio/data
cd ~/minio

cat > .env <<EOF
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=laios1855
EOF
chmod 600 .env

# 把仓库 docker-compose.yml 同步上来
docker compose pull
docker compose up -d

# 等健康检查通过
until docker compose ps minio | grep -q '(healthy)'; do sleep 3; done

# 预置 buckets（用容器内的 mc）
docker exec minio sh -c 'mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD'
docker exec minio mc mb -p local/offboarding-attachments local/offboarding-exports local/offboarding-screenshots
docker exec minio mc anonymous set download local/offboarding-screenshots
```

## 验证

```bash
# 从 Mac
curl -s http://192.168.2.44:9000/minio/health/live   # 期望 200
curl -s http://192.168.2.44:9001/                    # Web Console 静态文件
```

## 给离职流程系统准备 Service Account（推荐，不要用 root 凭证）

进入 Web Console → 左侧 **Access Keys** → **Create access key**：

- Access Key: `offboarding-flow`
- Secret Key: 自动生成（保存到 `hr/.env`）
- Policy: 自定义只允许操作 `offboarding-*` 三个 bucket

写到 `hr/.env`：

```env
MINIO_ENDPOINT=http://192.168.2.44:9000
MINIO_ACCESS_KEY=offboarding-flow
MINIO_SECRET_KEY=__from_console__
MINIO_BUCKET_ATTACHMENTS=offboarding-attachments
MINIO_BUCKET_EXPORTS=offboarding-exports
```

Python 端用法（aioboto3 / minio-py）：

```python
from minio import Minio
client = Minio("192.168.2.44:9000", access_key="offboarding-flow",
               secret_key=os.environ["MINIO_SECRET_KEY"], secure=False)
client.put_object("offboarding-attachments", f"{flow_id}/{filename}", data, length)
```

## 故障排查

| 现象 | 处理 |
|---|---|
| 9001 console 转跳到 IP 但访问超时 | 检查 `MINIO_BROWSER_REDIRECT_URL` 是否设为 `http://192.168.2.44:9001`（不是 localhost）|
| Mac 上传文件慢 | WSL2 + Docker Desktop 的网络栈对大文件 IO 不稳，建议大文件先 scp 到 WSL 再 `mc cp` |
| 磁盘紧张 | 数据卷在 `~/minio/data/`，可用 `mc ls local --recursive` 评估占用；定期 `mc rm --older-than` 清理 |
| 升级 MinIO | 修改 `docker-compose.yml` image tag → `docker compose pull && docker compose up -d`，数据卷不丢 |

## 回滚

```bash
cd ~/minio
docker compose down       # 保留数据
# 彻底清空：
# docker compose down && rm -rf ./data
```
