import { Button,Modal,Space } from 'antd'
import { DownloadOutlined,ReloadOutlined } from '@ant-design/icons'

export const LOCAL_ASSISTANT_DOWNLOAD_URL='/downloads/Jushu-Local-Assistant-Windows-v12.zip?v=20260814-religious-policy-v3'
export const LOCAL_ASSISTANT_DOWNLOAD_FILENAME='Jushu-Local-Assistant-Windows-v12.zip'

export function downloadLocalAssistantInstaller(){
  const link=document.createElement('a')
  link.href=LOCAL_ASSISTANT_DOWNLOAD_URL
  link.download=LOCAL_ASSISTANT_DOWNLOAD_FILENAME
  link.style.display='none'
  document.body.appendChild(link)
  link.click()
  window.setTimeout(()=>link.remove(),0)
}

export function showLocalAssistantInstallPrompt({mode='install'}:{mode?:'install'|'update'}={}){
  const updating=mode==='update'
  Modal.info({
    title:updating?'需要更新剧枢本地助手':'需要安装剧枢本地助手',
    width:520,
    okText:'关闭',
    content:<div className="local-assistant-prompt">
      <p>{updating?'当前助手版本不支持此功能，请安装最新版。':'本地助手用于读取当前使用者自己电脑里的视频文件夹。'}源视频不会上传服务器。</p>
      <div className="local-assistant-steps">
        <span><b>1</b><small>下载安装包并解压</small></span>
        <span><b>2</b><small>双击安装并自动启动</small></span>
        <span><b>3</b><small>回到网页重新检测</small></span>
      </div>
      <Space wrap>
        <Button type="primary" icon={<DownloadOutlined/>} href={LOCAL_ASSISTANT_DOWNLOAD_URL} download={LOCAL_ASSISTANT_DOWNLOAD_FILENAME}>{updating?'下载最新版':'下载 Windows 本地助手'}</Button>
        <Button icon={<ReloadOutlined/>} onClick={()=>window.location.reload()}>已经启动，重新检测</Button>
      </Space>
      <small className="local-assistant-note">首次安装需要联网下载视频处理组件；浏览器询问“本地网络访问”时请选择允许。</small>
    </div>,
  })
}

export function showLocalAssistantAccessPrompt(){
  Modal.warning({
    title:'请允许浏览器访问本地助手',
    width:540,
    okText:'我已允许，重新检测',
    onOk:()=>window.location.reload(),
    content:<div className="local-assistant-prompt">
      <p>网页当前没有连通本地助手。这通常是浏览器尚未允许“本地网络访问”，不代表安装失败。</p>
      <div className="local-assistant-steps">
        <span><b>1</b><small>点击地址栏左侧的网站图标</small></span>
        <span><b>2</b><small>将“本地网络访问”设为允许</small></span>
        <span><b>3</b><small>回到页面重新检测</small></span>
      </div>
      <Space wrap>
        <Button href="http://127.0.0.1:17862/api/local/health" target="_blank">检查助手运行状态</Button>
        <Button icon={<DownloadOutlined/>} href={LOCAL_ASSISTANT_DOWNLOAD_URL} download={LOCAL_ASSISTANT_DOWNLOAD_FILENAME}>确需重装时下载</Button>
      </Space>
      <small className="local-assistant-note">检查页面显示 status: ok，说明助手已经正常安装，只需处理浏览器权限。</small>
    </div>,
  })
}
