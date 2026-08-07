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
          colorPrimary:'#171b16', colorInfo:'#45a990', colorSuccess:'#78a83c', colorWarning:'#c59c26', colorError:'#cf5f5b',
          colorText:'#171b16', colorTextSecondary:'#737b72', colorBorder:'#dfe7da', colorBgLayout:'#f3f7f2',
          borderRadius:12, borderRadiusLG:17, controlHeight:38, fontFamily:'Inter, "Microsoft YaHei", sans-serif', fontSize:13,
        },
        components: {
          Button:{primaryShadow:'none',defaultShadow:'none',fontWeight:650},
          Card:{headerFontSize:14},
          Menu:{itemBorderRadius:10,itemHeight:42,itemSelectedBg:'#cff595',itemHoverBg:'#e9fff8',itemSelectedColor:'#171b16'},
          Segmented:{itemSelectedBg:'#cff595',trackBg:'#edf3e9'},
          Progress:{defaultColor:'#95c954',remainingColor:'#edf3e9'},
          Table:{headerBg:'#f5f9f1',headerColor:'#727970',rowHoverBg:'#f5fff9'}, Modal:{borderRadiusLG:20},
          Select:{
            activeBorderColor:'#78a83c',hoverBorderColor:'#9bc76a',activeOutlineColor:'rgba(207,245,149,.34)',
            optionActiveBg:'#e9fff8',optionSelectedBg:'#cff595',optionSelectedColor:'#171b16',
          },
        },
      }}
    >
      <BrowserRouter><App /></BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>,
)
