剧枢本地助手（Windows）

作用
1. 让 https://app.duanju.chat 选择当前使用者自己电脑里的视频文件夹。
2. 视频读取、内容加工和 Meta 文件夹生成均在这台电脑执行。
3. 网页只同步文件名、集数、大小和任务状态，不会因为安装助手而上传源视频。

安装
1. 解压本下载包。
2. 双击 Install-Jushu-Local-Assistant.cmd。
3. 首次安装会联网下载 Python、FFmpeg 和视频处理组件，耗时取决于网速。
4. 看到“安装完成”后，回到剧枢网页，点击“已经启动，重新检测”。
5. 浏览器首次询问“本地网络访问”时请选择允许。

启动与更新
- 安装后会在桌面创建“剧枢本地助手”快捷方式，并在登录 Windows 后自动启动。
- 再次运行本安装程序会更新助手代码，并保留本机工作区和已经生成的文件。

AI 识别
- 安装包不包含任何公共或服务器密钥。
- 已有云端识别结果会自动复用；如需在本机首次调用模型，请由管理员在
  %LOCALAPPDATA%\Jushu\assistant\settings.env 中配置 GEMINI_API_KEY 或 QWEN_API_KEY，
  然后重新启动桌面的“剧枢本地助手”。

本地数据位置
%LOCALAPPDATA%\Jushu\local-workspace

卸载
1. 在任务管理器结束正在运行的 python.exe（命令行中包含 backend.local_workspace）。
2. 删除 %LOCALAPPDATA%\Jushu\assistant。
3. 删除桌面和 Windows 启动文件夹中的“剧枢本地助手”快捷方式。
4. 如果也要删除本机工作记录和本机成品，再删除 %LOCALAPPDATA%\Jushu\local-workspace。
