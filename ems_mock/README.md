# Mock 共济 EMS — 使用说明

无真实共济 EMS 时，用本服务作为南向数据源联调「动环监控预警平台」。完全遵循《共济基础设施监控数据接入标准 V2.23》报文格式。

## 它能做什么
- 实现全部北向接口：login / heart / logout / get_space_list / get_device_list / get_spot_list / online_data_subscribe / online_data / offline_value / online_alarm_subscribe / offline_alarm / get_event_rules。
- 订阅后**每 10s** 主动向平台推送一轮全量实时数据（`/north/online_data_push`），并周期性注入**超限值**以触发平台规则引擎告警。
- 周期性向平台推送**设备级 EMS 事件**（通信中断 0 / 故障 21 / 停止采集 30）（`/north/online_alarm_push`），用于验证平台的「混合告警源」接入与去重。
- 内置样例拓扑：厦门数据中心 → 核心机房 → 1#UPS / 1#精密空调 / 1#温湿度 / 1#列头柜，共 11 个测点（温/湿/电压/电流/功率/负载/状态等）。

## 运行
```bash
pip install -r requirements.txt
uvicorn mock_ems_server:app --host 0.0.0.0 --port 9000
```
登录账号固定：**admin / 123456**（可在 `login` 里放宽）。

## 联调步骤
1. 起平台后端（含 `/north/online_data_push`、`/north/online_alarm_push` 两个接收端点），假设监听 `192.168.x.x:8000`。
2. 起本 mock（:9000）。
3. 平台「系统设置 → EMS 连接」配置：
   - base_url：`http://<mock_host>:9000`
   - username/password：`admin` / `123456`
   - recv_ip / recv_port：平台后端**对外可达**的接收地址（如 `192.168.x.x` / `8000`）
   - version：`20170714124155`
4. 平台触发：登录 → 配置同步 → 订阅数据 + 订阅告警。
5. 观察：平台开始每 10s 收到推送、大盘实时刷新；偶发超限触发平台告警；偶发设备级事件进入告警中心。

> 注意：mock 是按 login 时上报的 recv_ip:recv_port 反向 POST 推送的。容器/跨机联调时，确保该地址从 mock 侧网络可达（不要填 127.0.0.1，除非同机同网络命名空间）。

## 验证要点对照
- **采集**：平台持续接收 10s 周期数据并落库。
- **预警（平台引擎）**：注入的超限模拟量被平台规则引擎捕获、去抖、分级、走通知。
- **EMS 告警接入**：通信中断/故障/停采进入告警中心；若 mock 改为也推过高(2)类告警，应被平台去重。
- **历史/回补**：调用 `offline_value` 返回按 interval 粒度的历史点；超过 100 测点或跨度 >1 天会返回参数错误（验证平台分批分片逻辑）。
- **断连重连**：停掉 mock 再起，平台应自动重登并重订阅。

## 可调项（按需改 mock_ems_server.py）
- `POINTS`：增减设备/测点、改基准值与触发阈值 `hi`。
- `_push_loop` 周期（默认 10s）、`_maybe_inject` 注入概率。
- `_alarm_loop` 设备级事件类型与频率。
