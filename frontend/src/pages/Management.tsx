import { useState } from 'react'
import { Segmented, Typography } from 'antd'
import { ExperimentOutlined, FolderOpenOutlined, LinkOutlined, RadarChartOutlined } from '@ant-design/icons'
import Matrix from './Matrix'
import Strategies from './Strategies'
import LocalFileManager from './LocalFileManager'
import RadarAccounts from './RadarAccounts'

export default function Management(){
  const[tab,setTab]=useState<'accounts'|'monitored'|'strategies'|'files'>('accounts')
  return <div className="workspace-page management-page">
    <div className="page-heading page-heading-rich"><Typography.Title level={2}>管理</Typography.Title><Segmented size="large" value={tab} onChange={value=>setTab(value as typeof tab)} options={[{value:'accounts',label:'账号连接',icon:<LinkOutlined/>},{value:'monitored',label:'监测账号',icon:<RadarChartOutlined/>},{value:'strategies',label:'账号运营策略',icon:<ExperimentOutlined/>},{value:'files',label:'文件管理',icon:<FolderOpenOutlined/>}]}/></div>
    {tab==='accounts'?<Matrix embedded/>:tab==='monitored'?<RadarAccounts/>:tab==='strategies'?<Strategies embedded/>:<LocalFileManager/>}
  </div>
}
