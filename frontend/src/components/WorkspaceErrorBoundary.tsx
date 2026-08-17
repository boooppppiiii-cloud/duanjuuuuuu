import { Component,type ErrorInfo,type ReactNode } from 'react'
import { Alert,Button,Space } from 'antd'

type Props={children:ReactNode;resetKey:string}
type State={error:Error|null}

export class WorkspaceErrorBoundary extends Component<Props,State>{
  state:State={error:null}

  static getDerivedStateFromError(error:Error):State{return{error}}

  componentDidCatch(error:Error,info:ErrorInfo){
    console.error('Workspace render failed',error,info)
  }

  componentDidUpdate(previous:Props){
    if(this.state.error&&previous.resetKey!==this.props.resetKey)this.setState({error:null})
  }

  render(){
    if(!this.state.error)return this.props.children
    return <div className="workspace-error-state">
      <Alert showIcon type="error" message="页面显示出现异常" description="任务仍在后台保存。恢复页面不会重新消耗已经完成的识别进度。"/>
      <Space wrap>
        <Button type="primary" onClick={()=>window.location.reload()}>恢复当前页面</Button>
        <Button onClick={()=>{window.location.href='/'}}>返回账号总览</Button>
      </Space>
    </div>
  }
}
