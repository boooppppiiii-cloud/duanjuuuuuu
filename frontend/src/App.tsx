import { lazy,Suspense,useEffect,useMemo,useState } from 'react'
import { BarChartOutlined,DashboardOutlined,ExperimentOutlined,FolderOpenOutlined,LogoutOutlined,RadarChartOutlined,SendOutlined,SettingOutlined } from '@ant-design/icons'
import { Button,Layout,Menu,Spin,Tooltip } from 'antd'
import { Navigate,Route,Routes,useLocation,useNavigate } from 'react-router-dom'
import { PlatformLogo } from './components/PlatformBrand'
import { JushuLogo } from './components/JushuLogo'
import { WorkspaceErrorBoundary } from './components/WorkspaceErrorBoundary'
import { api,type AuthUser } from './api'
import { AuthContext } from './auth'
import AuthPage from './pages/AuthPage'
import { flushTelemetry } from './telemetry'

const loadDashboard=()=>import('./pages/Dashboard')
const loadDramaLibrary=()=>import('./pages/DramaLibrary')
const loadDramaDetail=()=>import('./pages/DramaDetail')
const loadContentFactory=()=>import('./pages/ContentFactory')
const loadPublishingCenter=()=>import('./pages/PublishingCenter')
const loadManagement=()=>import('./pages/Management')
const loadMetaDelivery=()=>import('./pages/MetaDelivery')
const loadDeveloperAnalytics=()=>import('./pages/DeveloperAnalytics')
const loadRadar=()=>import('./pages/Radar')

const DashboardPage=lazy(loadDashboard)
const DramaLibrary=lazy(loadDramaLibrary)
const DramaDetail=lazy(loadDramaDetail)
const ContentFactory=lazy(loadContentFactory)
const PublishingCenter=lazy(loadPublishingCenter)
const Management=lazy(loadManagement)
const MetaDelivery=lazy(loadMetaDelivery)
const DeveloperAnalytics=lazy(loadDeveloperAnalytics)
const Radar=lazy(loadRadar)
const nav=[
 {key:'radar',icon:<RadarChartOutlined/>,label:'平台动态'},
 {key:'home',icon:<DashboardOutlined/>,label:'账号总览'},
 {key:'dramas',icon:<FolderOpenOutlined/>,label:'剧库'},
 {key:'factory',icon:<ExperimentOutlined/>,label:'内容工厂'},
 {key:'publishing',icon:<SendOutlined/>,label:'一键发布'},
 {key:'management',icon:<SettingOutlined/>,label:'管理'},
 {key:'meta-delivery',icon:<PlatformLogo platform="meta" size={17}/>,label:'Meta 官方投递',className:'meta-nav-item'},
]
export default function App(){
 const navigate=useNavigate();const location=useLocation();const[collapsed,setCollapsed]=useState(()=>window.innerWidth<880);const[user,setUser]=useState<AuthUser|null|undefined>(undefined)
 useEffect(()=>{api.authMe().then(result=>setUser(result.user)).catch(()=>setUser(null));const expired=()=>setUser(null);window.addEventListener('jushu:unauthorized',expired);return()=>window.removeEventListener('jushu:unauthorized',expired)},[])
 useEffect(()=>{if(user)void flushTelemetry()},[user])
 useEffect(()=>{window.scrollTo({top:0,left:0,behavior:'instant'})},[location.pathname])
 const active=useMemo(()=>{const first=location.pathname.split('/')[1];return first||'home'},[location.pathname])
 const jump=(key:string)=>navigate(key==='home'?'/':`/${key}`)
 const logout=async()=>{try{await api.logout()}finally{setUser(null);navigate('/')}}
 if(user===undefined)return <div className="app-bootstrap"><Spin size="large"/></div>
 if(!user)return <AuthPage onAuthenticated={setUser}/>
 const visibleNav=user.is_developer?[...nav,{key:'developer',icon:<BarChartOutlined/>,label:'开发者数据'}]:nav
 return <AuthContext.Provider value={{user,logout}}><Layout className={`app-shell ${collapsed?'is-sidebar-collapsed':''}`}>
  <Layout.Sider className="sidebar" width={224} collapsedWidth={68} collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="light">
   <div className={`brand ${collapsed?'is-collapsed':''}`}><JushuLogo size={40}/>{!collapsed&&<div><b>剧枢</b><small>DRAMA OPS HUB</small></div>}</div>
    <Menu mode="inline" selectedKeys={[active]} items={visibleNav} onClick={({key})=>jump(String(key))}/>
    <div className="sidebar-account"><div><b>{collapsed?user.email[0].toUpperCase():user.email.split('@')[0]}</b>{!collapsed&&<span>{user.email}</span>}</div><Tooltip title="退出登录"><Button type="text" icon={<LogoutOutlined/>} onClick={logout}/></Tooltip></div>
  </Layout.Sider>
  <Layout className="main-layout">
   <Layout.Content className="content"><WorkspaceErrorBoundary resetKey={location.pathname}><Suspense fallback={<div className="route-loading"><Spin size="large"/><span>正在加载工作区…</span></div>}><Routes>
     <Route path="/" element={<DashboardPage/>}/><Route path="/dramas" element={<DramaLibrary/>}/><Route path="/dramas/:id" element={<DramaDetail/>}/><Route path="/radar" element={<Radar/>}/><Route path="/radar/dramas/:id" element={<Radar/>}/><Route path="/radar/accounts" element={<Radar/>}/><Route path="/radar/cases" element={<Radar/>}/><Route path="/factory" element={<ContentFactory/>}/><Route path="/publishing" element={<PublishingCenter/>}/><Route path="/management" element={<Management/>}/><Route path="/meta-delivery" element={<MetaDelivery/>}/>
     <Route path="/developer" element={user.is_developer?<DeveloperAnalytics/>:<Navigate to="/" replace/>}/>
    <Route path="/production" element={<Navigate to="/factory" replace/>}/><Route path="/visual-moderation" element={<Navigate to="/factory" replace/>}/><Route path="/creative" element={<Navigate to="/publishing" replace/>}/><Route path="/publish" element={<Navigate to="/publishing" replace/>}/><Route path="/matrix" element={<Navigate to="/management" replace/>}/><Route path="/strategies" element={<Navigate to="/management" replace/>}/><Route path="/metrics" element={<Navigate to="/" replace/>}/><Route path="/engagement" element={<Navigate to="/" replace/>}/><Route path="/library" element={<Navigate to="/dramas" replace/>}/><Route path="/operations" element={<Navigate to="/management" replace/>}/><Route path="*" element={<Navigate to="/" replace/>}/>
   </Routes></Suspense></WorkspaceErrorBoundary></Layout.Content>
  </Layout>
  </Layout></AuthContext.Provider>
}
