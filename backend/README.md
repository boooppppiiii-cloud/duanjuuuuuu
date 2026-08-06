# 后端

FastAPI + SQLModel 单体服务。`app/models.py` 保存 P0 全量核心数据模型；`app/routers/` 按业务拆分接口；`app/services/` 放可测试的业务逻辑。应用启动时自动建表。

里程碑 1 的剧库扫描只读取 `MEDIA_ROOT/dramas`，不会删除磁盘文件或数据库记录。重复扫描按剧目目录更新集数与路径。

