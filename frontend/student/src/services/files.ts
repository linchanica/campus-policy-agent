export async function downloadOriginal(key:string){
  const base=import.meta.env.VITE_API_BASE_URL||''
  const token=uni.getStorageSync('policy_token')||''
  // #ifdef H5
  const response=await fetch(base+'/api/v1/attachments/'+key,{headers:{Authorization:'Bearer '+token}})
  if(!response.ok)throw new Error('原件暂不可下载')
  const blob=await response.blob();const href=URL.createObjectURL(blob);const a=document.createElement('a');a.href=href
  const disposition=response.headers.get('content-disposition')||''
  const match=disposition.match(/filename\*=utf-8''([^;]+)/i)
  a.download=match?decodeURIComponent(match[1]):key+'.docx';a.click();setTimeout(()=>URL.revokeObjectURL(href),1000)
  return
  // #endif
  // #ifdef MP-WEIXIN
  return new Promise<void>((resolve,reject)=>uni.downloadFile({url:(base||'http://127.0.0.1:8000')+'/api/v1/attachments/'+key,header:{Authorization:'Bearer '+token},success(r){if(r.statusCode!==200){reject(new Error('下载失败'));return}uni.openDocument({filePath:r.tempFilePath,showMenu:true,success(){resolve()},fail(){reject(new Error('请在开发工具或真机检查文件预览与域名配置'))}})},fail(){reject(new Error('无法下载原件，请确认服务与域名配置'))}}))
  // #endif
}

