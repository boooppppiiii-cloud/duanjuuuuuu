# 发布通道

所有发布实现必须继承 `PublishChannel`。注册表是平台切换的唯一入口；YouTube、TikTok、Facebook 与 Instagram 均调用官方接口，只有拿到可追踪的平台 ID 才能进入已提交或已发布状态。
