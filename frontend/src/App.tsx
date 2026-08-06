import { lazy,Suspense,useEffect,useMemo,useState } from 'react'
import { CloudUploadOutlined,DashboardOutlined,ExperimentOutlined,FolderOpenOutlined,SendOutlined,SettingOutlined } from '@ant-design/icons'
import { Layout,Menu,Spin,Tag } from 'antd'
import { Navigate,Route,Routes,useLocation,useNavigate } from 'react-router-dom'

const DashboardPage=lazy(()=>import('./pages/Dashboard'))
const DramaLibrary=lazy(()=>import('./pages/DramaLibrary'))
const DramaDetail=lazy(()=>import('./pages/DramaDetail'))
const ContentFactory=lazy(()=>import('./pages/ContentFactory'))
const PublishingCenter=lazy(()=>import('./pages/PublishingCenter'))
const Management=lazy(()=>import('./pages/Management'))
const MetaDelivery=lazy(()=>import('./pages/MetaDelivery'))

const nav=[
 {key:'home',icon:<DashboardOutlined/>,label:'首页'},
 {key:'dramas',icon:<FolderOpenOutlined/>,label:'剧库'},
 {key:'factory',icon:<ExperimentOutlined/>,label:'内容工厂'},
 {key:'publishing',icon:<SendOutlined/>,label:'一键发布'},
 {key:'management',icon:<SettingOutlined/>,label:'管理'},
 {key:'meta-delivery',icon:<CloudUploadOutlined/>,label:'Meta 官方投递',className:'meta-nav-item'},
]
export default function App(){
 const navigate=useNavigate();const location=useLocation();const[collapsed,setCollapsed]=useState(()=>window.innerWidth<880)
 useEffect(()=>{window.scrollTo({top:0,left:0,behavior:'instant'})},[location.pathname])
 const active=useMemo(()=>{const first=location.pathname.split('/')[1];return first||'home'},[location.pathname])
 const jump=(key:string)=>navigate(key==='home'?'/':`/${key}`)
 return <Layout className="app-shell">
  <Layout.Sider className="sidebar" width={224} collapsedWidth={68} collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="light">
   <div className="brand"><span className="brand-mark">媒</span>{!collapsed&&<div><b>社媒中心</b><small>SOCIAL OPS CENTER</small></div>}</div>
   <Menu mode="inline" selectedKeys={[active]} items={nav} onClick={({key})=>jump(String(key))}/>
   {!collapsed&&<div className="sidebar-foot"><Tag>LOCAL</Tag><div><b>本地工作流</b><small>真实数据 · 官方接口</small></div></div>}
  </Layout.Sider>
  <Layout className="main-layout">
   <Layout.Content className="content"><Suspense fallback={<div className="route-loading"><Spin size="large"/><span>正在加载工作区…</span></div>}><Routes>
    <Route path="/" element={<DashboardPage/>}/><Route path="/dramas" element={<DramaLibrary/>}/><Route path="/dramas/:id" element={<DramaDetail/>}/><Route path="/factory" element={<ContentFactory/>}/><Route path="/publishing" element={<PublishingCenter/>}/><Route path="/management" element={<Management/>}/><Route path="/meta-delivery" element={<MetaDelivery/>}/>
    <Route path="/production" element={<Navigate to="/factory" replace/>}/><Route path="/visual-moderation" element={<Navigate to="/factory" replace/>}/><Route path="/creative" element={<Navigate to="/publishing" replace/>}/><Route path="/publish" element={<Navigate to="/publishing" replace/>}/><Route path="/matrix" element={<Navigate to="/management" replace/>}/><Route path="/strategies" element={<Navigate to="/management" replace/>}/><Route path="/metrics" element={<Navigate to="/" replace/>}/><Route path="/engagement" element={<Navigate to="/" replace/>}/><Route path="/library" element={<Navigate to="/dramas" replace/>}/><Route path="/operations" element={<Navigate to="/management" replace/>}/><Route path="*" element={<Navigate to="/" replace/>}/>
   </Routes></Suspense></Layout.Content>
  </Layout>
 </Layout>
}
