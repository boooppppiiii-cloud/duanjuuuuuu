import { useCallback,useEffect,useState } from 'react'
import { Alert,Button,Card,Empty,message,Popconfirm,Space,Statistic,Table,Tag,Typography } from 'antd'
import { DeleteOutlined,DownloadOutlined,FolderOpenOutlined,ReloadOutlined } from '@ant-design/icons'
import { localAssistantSupports,localAssistantUnavailable,localWorkspace,LocalStorageItem,LocalStorageSummary } from '../localWorkspace'
import { LOCAL_ASSISTANT_DOWNLOAD_FILENAME,LOCAL_ASSISTANT_DOWNLOAD_URL,showLocalAssistantAccessPrompt } from '../components/LocalAssistantPrompt'

const STORAGE_CAPABILITY='local_storage_manager_v1'
const bytes=(value:number)=>value>=1024**3?`${(value/1024**3).toFixed(2)} GB`:value>=1024**2?`${(value/1024**2).toFixed(1)} MB`:value>=1024?`${(value/1024).toFixed(1)} KB`:`${value} B`
const category:Record<LocalStorageItem['category'],{label:string;color:string}>={
  processing:{label:'加工缓存',color:'blue'},analysis:{label:'识别缓存',color:'purple'},material:{label:'素材副本',color:'orange'},cache:{label:'常规缓存',color:'default'},model:{label:'本机模型',color:'cyan'},
}

export default function LocalFileManager(){
  const[msg,holder]=message.useMessage()
  const[summary,setSummary]=useState<LocalStorageSummary>()
  const[state,setState]=useState<'checking'|'ready'|'offline'|'outdated'|'error'>('checking')
  const[issue,setIssue]=useState('')
  const[deleting,setDeleting]=useState('')

  const load=useCallback(async(force=false)=>{
    setState('checking');setIssue('')
    try{
      const health=force?await localWorkspace.requestAccess():await localWorkspace.health()
      if(!localAssistantSupports(health,STORAGE_CAPABILITY)){setState('outdated');setIssue('当前版本不支持文件管理，请更新本地助手。');return}
      setSummary(await localWorkspace.storage());setState('ready')
    }catch(error){
      const text=(error as Error).message
      setIssue(text);setState(localAssistantUnavailable(error)?'offline':'error')
    }
  },[])

  useEffect(()=>{load().catch(()=>undefined)},[load])

  const remove=async(item:LocalStorageItem)=>{
    setDeleting(item.id)
    try{
      const result=await localWorkspace.deleteStorage(item.id)
      setSummary(result);setState('ready');msg.success(`已释放 ${bytes(result.freed_bytes)}`)
    }catch(error){msg.error((error as Error).message)}finally{setDeleting('')}
  }

  return <div className="management-inner local-file-manager">{holder}
    <Alert type="info" showIcon message="这里只管理当前电脑上的可清理文件" description="源视频和正式生成的成品不会被当作缓存列出，也不会被自动删除。服务器上其他用户的数据不会显示在这里。"/>
    {state!=='ready'&&<Card>
      {state==='checking'
        ?<Typography.Text type="secondary">正在读取当前电脑的文件占用…</Typography.Text>
        :<Alert type={state==='error'?'error':'warning'} showIcon message={state==='outdated'?'需要更新本地助手':'暂时无法读取本机文件'} description={issue||'请确认本地助手已经启动。'} action={<Space wrap>{state==='outdated'?<Button type="primary" icon={<DownloadOutlined/>} href={LOCAL_ASSISTANT_DOWNLOAD_URL} download={LOCAL_ASSISTANT_DOWNLOAD_FILENAME}>下载最新版</Button>:<Button type="primary" onClick={()=>{showLocalAssistantAccessPrompt();load(true).catch(()=>undefined)}}>允许本地访问并重试</Button>}<Button icon={<ReloadOutlined/>} onClick={()=>load(true)}>重新检测</Button></Space>}/>
      }
    </Card>}
    {state==='ready'&&<>
      <div className="local-storage-summary">
        <Card><Statistic title="可管理文件" value={summary?.item_count??0} suffix="项"/></Card>
        <Card><Statistic title="占用空间" value={bytes(summary?.total_bytes??0)}/></Card>
        <Card><Space direction="vertical" size={2}><Typography.Text type="secondary">本地助手目录</Typography.Text><Typography.Text ellipsis={{tooltip:summary?.workspace_root}}><FolderOpenOutlined/> {summary?.workspace_root}</Typography.Text></Space></Card>
        <Button icon={<ReloadOutlined/>} onClick={()=>load(true)}>刷新</Button>
      </div>
      <Card className="table-card" title="本机文件">
        <Table<LocalStorageItem> rowKey="id" dataSource={summary?.items??[]} pagination={false} locale={{emptyText:<Empty description="当前没有可清理文件"/>}} scroll={{x:980}} columns={[
          {title:'类型',width:105,render:(_,row)=><Tag color={category[row.category].color}>{category[row.category].label}</Tag>},
          {title:'文件',width:250,render:(_,row)=><Space direction="vertical" size={0}><b>{row.name}</b>{row.drama_title&&<Typography.Text type="secondary">{row.drama_title}</Typography.Text>}</Space>},
          {title:'用途',dataIndex:'description',width:280,render:(value:string,row)=><Space direction="vertical" size={2}><span>{value}</span>{row.warning&&<Typography.Text type="warning">{row.warning}</Typography.Text>}</Space>},
          {title:'占用',width:110,render:(_,row)=><Space direction="vertical" size={0}><b>{bytes(row.size_bytes)}</b><Typography.Text type="secondary">{row.file_count} 个文件</Typography.Text></Space>},
          {title:'位置',dataIndex:'path',width:260,ellipsis:{showTitle:false},render:(value:string)=><Typography.Text ellipsis={{tooltip:value}}>{value}</Typography.Text>},
          {title:'操作',width:100,fixed:'right',render:(_,row)=><Popconfirm title="确认删除这项本机文件？" description={row.warning||'删除后无法从回收站恢复。'} okText="确认删除" okButtonProps={{danger:true}} cancelText="取消" onConfirm={()=>remove(row)}><Button danger icon={<DeleteOutlined/>} loading={deleting===row.id}>删除</Button></Popconfirm>},
        ]}/>
      </Card>
    </>}
  </div>
}
