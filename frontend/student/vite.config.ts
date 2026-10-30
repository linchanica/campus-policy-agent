import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'
export default defineConfig({
  base:'./',
  plugins:[uni()],
  server:{host:'127.0.0.1',port:5173,proxy:{'/api':'http://127.0.0.1:8000','/health':'http://127.0.0.1:8000'}}
})

