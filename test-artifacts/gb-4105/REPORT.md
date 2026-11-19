# 阈值扫描（sweep）实现与本轮验证

## 改动概要
- `backend/src/services/operators.py`：把逐步算子抽成 `_apply`，新增 `execute_prefix`（共用前缀只跑一次）、`execute_from`（从已物化行继续跑后缀，保留每步证据）、`sweep_partition`（按该步输入的实际数值切分阈值域，用原 gte/lte 比较取代表阈值）。`execute` 行为与输出结构不变。
- `backend/src/models/sweep.py`、`services/sweeps.py`、`routes/sweeps.py`、`schemas.business.SweepInput`、`controllers.business`：新增 sweeps 实体与 `GET /sweeps`、`POST /sweeps`、`GET /sweeps/{id}`、`POST /sweeps/{id}/resume`。
- `backend/src/worker.py`：同时消费 `operator-sweeps` 队列。
- `frontend/src/components/sweep.js` + `pages/results.js` + `stores/api/constants/styles`：剖面页新增“阈值—分组对照”，已发布区间先显示，其余标待算，可展开完整结果、中断续跑、查看扫描进度。
- README 与 migrations 说明补充。

## 关键语义
- 只换所选 filter 步骤的阈值；比较方式、重复键倍数、连接后聚合、10000 行超限均复用原 `_apply`。
- 区间边界为数据中的实际数值，代表阈值按原比较方式求值（gte 含界，lte 含界），单段结果与整份计划执行逐行一致。
- 共用前缀 `execute_prefix` 只算一次，每个区间只跑阈值及其后缀，不重跑整份计划。
- 合并判据是“完整最终结果”（全部输出行 + checksum）相同；只改 `status`/`merged_into`，不重写任何已发布区间的 `lower/upper` 边界。
- 扫描把区间账本存在 `sweeps.data`，每个区间独立提交并推进 `next_index`；中断后 resume 从游标续跑，已确认区间直接跳过，不会重复发布。
- 超限区间标 `failed` 并保留其余区间结果；`coverage_complete` 仅在全部区间 published/merged 时为真，此时扫描状态为 `completed`。

## 验证（test-artifacts/gb-4105）
- `sweep_full_check.py`：合并、聚合后筛选、模拟硬中断后续跑、幂等 resume、超限 + 重试。结果：ALL PASS。
- `sweep_api_check.py`：鉴权（401/403/404/409/400）、列表摘要、详情分组、worker 执行后状态与覆盖、已完成重复 resume。结果：API CHECK PASS。
- `sweep_group_check.py`：相邻合并分组与“两侧都相同”的桥接分组，边界不被改写。结果：group helpers ok。
- 前端：全部 ES module 通过 `node --check`；sweep 组件在 node 下渲染校验（已发布/合并/待算行、按钮、新建表单）。

注：本环境无 Docker/PostgreSQL/Redis，服务层测试用 SQLite + 假队列驱动；容器化启动与真实 Redis 队列未在本机执行。
