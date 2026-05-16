-- 在 offboarding-postgres 容器首次启动时执行（挂到 /docker-entrypoint-initdb.d/）
-- 创建业务 schema (app) + LangGraph schema (langgraph) + 测试用 schema（_test 后缀）
-- 同时设定 flow 角色的默认 search_path

CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION flow;
CREATE SCHEMA IF NOT EXISTS langgraph AUTHORIZATION flow;
CREATE SCHEMA IF NOT EXISTS app_test AUTHORIZATION flow;
CREATE SCHEMA IF NOT EXISTS langgraph_test AUTHORIZATION flow;

-- 默认 search_path：业务连接走 app，public 兜底
-- 注意：LangGraph 连接显式指定 schema=langgraph，不依赖 search_path
ALTER ROLE flow SET search_path TO app, public;

-- 创建 uuid-ossp 扩展（PG 16 内置 gen_random_uuid，但留 uuid-ossp 兜底兼容旧 SQL）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA public;
