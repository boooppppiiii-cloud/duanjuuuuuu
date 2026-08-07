import { Typography } from 'antd'
import Publish from './Publish'

export default function PublishingCenter(){
 return <div className="workspace-page publishing-center">
  <div className="page-heading"><Typography.Title level={2}>一键发布</Typography.Title></div>
  <Publish embedded/>
 </div>
}
