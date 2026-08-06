import { useState } from 'react'
import { Segmented, Typography } from 'antd'
import { EditOutlined, RocketOutlined } from '@ant-design/icons'
import Creative from './Creative'
import Publish from './Publish'

export default function PublishingCenter(){
  const[stage,setStage]=useState<'edit'|'release'>('edit')
  return <div className="workspace-page publishing-center">
    <div className="page-heading"><Typography.Title level={2}>一键发布</Typography.Title></div>
    <Segmented block className="overview-pager publishing-pager" value={stage} onChange={v=>setStage(v as typeof stage)} options={[{value:'edit',label:'发布内容编辑',icon:<EditOutlined/>},{value:'release',label:'正式发布',icon:<RocketOutlined/>}]}/>
    {stage==='edit'?<Creative embedded/>:<Publish embedded/>}
  </div>
}
