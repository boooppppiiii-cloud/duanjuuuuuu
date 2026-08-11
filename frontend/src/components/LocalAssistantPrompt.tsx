import { Button,Modal,Space } from 'antd'
import { DownloadOutlined,ReloadOutlined } from '@ant-design/icons'

export const LOCAL_ASSISTANT_DOWNLOAD_URL='/downloads/Jushu-Local-Assistant-Windows-v2.zip?v=20260811-standalone'

export function downloadLocalAssistantInstaller(){
  const link=document.createElement('a')
  link.href=LOCAL_ASSISTANT_DOWNLOAD_URL
  link.download='Jushu-Local-Assistant-Windows-v2.zip'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export function showLocalAssistantInstallPrompt({autoDownload=false}:{autoDownload?:boolean}={}){
  if(autoDownload)downloadLocalAssistantInstaller()
  Modal.info({
    title:'需要安装剧枢本地助手',
    width:520,
    okText:'关闭',
    content:<div className="local-assistant-prompt">
      <p>{autoDownload?'安装包已开始下载。':'本地助手用于读取当前使用者自己电脑里的视频文件夹。'}源视频不会上传服务器。</p>
      <div className="local-assistant-steps">
        <span><b>1</b><small>下载安装包并解压</small></span>
        <span><b>2</b><small>双击安装并自动启动</small></span>
        <span><b>3</b><small>回到网页重新检测</small></span>
      </div>
      <Space wrap>
        <Button type="primary" icon={<DownloadOutlined/>} onClick={downloadLocalAssistantInstaller}>{autoDownload?'没有下载？重新下载':'下载 Windows 本地助手'}</Button>
        <Button icon={<ReloadOutlined/>} onClick={()=>window.location.reload()}>已经启动，重新检测</Button>
      </Space>
      <small className="local-assistant-note">首次安装需要联网下载视频处理组件；浏览器询问“本地网络访问”时请选择允许。</small>
    </div>,
  })
}
