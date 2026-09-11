import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

// 主题预初始化：手动选择优先，未选择时跟随系统（渲染前设置，避免首帧闪烁）
try {
  const savedTheme = localStorage.getItem('pe_theme')
  if (savedTheme === 'dark' || savedTheme === 'light') {
    document.documentElement.dataset.theme = savedTheme
  }
} catch {
  // ignore storage access errors
}

const root = document.getElementById('root')

if (!root) {
  throw new Error('Missing root element')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
