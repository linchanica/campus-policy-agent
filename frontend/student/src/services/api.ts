let base=import.meta.env.VITE_API_BASE_URL || ''
// #ifdef MP-WEIXIN
base=import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
// #endif
export class ApiError extends Error {status:number;constructor(message:string,status:number){super(message);this.status=status}}
export function call<T=any>(path:string,method:'GET'|'POST'|'DELETE'='GET',data?:any):Promise<T>{
  return new Promise((resolve,reject)=>uni.request({url:base+path,method,data,timeout:35000,header:{'Content-Type':'application/json','Authorization':'Bearer '+(uni.getStorageSync('policy_token')||'')},success(res){if(res.statusCode>=200&&res.statusCode<300)resolve(res.data as T);else {const b:any=res.data;reject(new ApiError(b?.detail?.message||b?.message||'请求暂时失败',res.statusCode))}},fail(){reject(new ApiError('暂时无法连接政策服务，请确认本地后端已启动。',0))}}))
}
export async function ensureGuest(){const expiry=uni.getStorageSync('policy_token_expires');if(expiry&&Date.parse(expiry)<=Date.now()){uni.removeStorageSync('policy_token');uni.removeStorageSync('policy_token_expires')}if(!uni.getStorageSync('policy_token')){const r=await call('/api/v1/auth/guest','POST');uni.setStorageSync('policy_token',r.access_token);uni.setStorageSync('policy_token_expires',r.expires_at);return true}return false}
export const uid=()=>Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,12)
export const delay=(ms:number)=>new Promise(r=>setTimeout(r,ms))
