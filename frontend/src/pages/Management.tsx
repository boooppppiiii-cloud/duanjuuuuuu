import { useState } from 'react'
import { Segmented, Typography } from 'antd'
import { ExperimentOutlined, LinkOutlined } from '@ant-design/icons'
import Matrix from './Matrix'
import Strategies from './Strategies'

export default function Management(){
  const[tab,setTab]=useState<'accounts'|'strategies'>('accounts')
  return <div className="workspace-page management-page">
    <div className="page-heading page-heading-rich"><Typography.Title level={2}>管理</Typography.Title><Segmented size="large" value={tab} onChange={value=>setTab(value as typeof tab)} options={[{value:'accounts',label:'账号连接',icon:<LinkOutlined/>},{value:'strategies',label:'账号运营策略',icon:<ExperimentOutlined/>}]}/></div>
    {tab==='accounts'?<Matrix embedded/>:<Strategies embedded/>}
  </div>
}
