import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary:'#171b16', colorInfo:'#6f8f97', colorSuccess:'#73a942', colorWarning:'#d88955', colorError:'#cf5f5b',
          colorText:'#171b16', colorTextSecondary:'#737b72', colorBorder:'#e6e9e3', colorBgLayout:'#f2f4f1',
          borderRadius:12, borderRadiusLG:17, controlHeight:38, fontFamily:'Inter, "Microsoft YaHei", sans-serif', fontSize:13,
        },
        components: {
          Button:{primaryShadow:'none',defaultShadow:'none',fontWeight:650},
          Card:{headerFontSize:14}, Menu:{itemBorderRadius:10,itemHeight:42},
          Table:{headerBg:'#f7f8f5',headerColor:'#727970',rowHoverBg:'#fafbf8'}, Modal:{borderRadiusLG:20},
        },
      }}
    >
      <BrowserRouter><App /></BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>,
)
