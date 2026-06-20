"""报表模块（Sprint 6）：告警统计聚合、数据/告警导出、定时邮件报表。

模块边界（红线 #6.2）：仅依赖 core（Shared Kernel）与 models（数据层），
不反向耦合 engine/notify 等 Feature 的业务逻辑；邮件解密直接用 core.crypto。
"""
