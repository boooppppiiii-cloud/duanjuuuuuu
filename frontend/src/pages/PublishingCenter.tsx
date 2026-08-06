import { useState } from 'react'
import { Segmented, Tabs, Typography } from 'antd'
import { CloudUploadOutlined, EditOutlined, RocketOutlined, SendOutlined } from '@ant-design/icons'
import Creative from './Creative'
import MetaDelivery from './MetaDelivery'
import Publish from './Publish'

export default function PublishingCenter(){
  const[stage,setStage]=useState<'edit'|'release'>('edit')
  const[channel,setChannel]=useState('social')
  return <div className="workspace-page publishing-center">
    <div className="page-heading page-heading-rich"><Typography.Title level={2}>一键发布</Typography.Title><Segmented size="large" value={stage} onChange={v=>setStage(v as typeof stage)} options={[{value:'edit',label:'发布内容编辑',icon:<EditOutlined/>},{value:'release',label:'正式发布',icon:<RocketOutlined/>}]}/></div>
    {stage==='edit'?<Creative embedded/>:<Tabs className="module-tabs release-tabs" activeKey={channel} onChange={setChannel} items={[
      {key:'social',label:<span><SendOutlined/>普通社媒一键发布</span>,children:<Publish embedded/>},
      {key:'meta',label:<span><CloudUploadOutlined/>Meta 官方投递</span>,children:<MetaDelivery embedded/>},
    ]}/>} 
  </div>
}
