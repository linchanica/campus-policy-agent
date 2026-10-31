let base=import.meta.env.VITE_API_BASE_URL || ''
// #ifdef MP-WEIXIN
base=import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
// #endif
export class ApiError extends Error {status:number;constructor(message:string,status:number){super(message);this.status=status}}
export function call<T=any>(path:string,method:'GET'|'POST'|'DELETE'='GET',data?:any):Promise<T>{
  return new Promise((resolve,reject)=>uni.request({url:base+path,method,data,timeout:35000,header:{'Content-Type':'application/json','Authorization':'Bearer '+(uni.getStorageSync('policy_token')||'')},success(res){if(res.statusCode>=200&&res.statusCode<300)resolve(res.data as T);else {const b:any=res.data;reject(new ApiError(b?.detail?.message||b?.message||'请求暂时失败',res.statusCode))}},fail(){reject(new ApiError('暂时无法连接政策服务，请确认本地后端已启动。',0))}}))
}
export function clearAuth(){for(const key of ['policy_token','policy_token_expires','policy_auth_mode'])uni.removeStorageSync(key)}
export function storeAuth(r:any){uni.setStorageSync('policy_token',r.access_token);uni.setStorageSync('policy_token_expires',r.expires_at);uni.setStorageSync('policy_auth_mode',r.auth_mode)}
export async function ensureGuest(){const expiry=uni.getStorageSync('policy_token_expires');if(expiry&&Date.parse(expiry)<=Date.now())clearAuth();if(!uni.getStorageSync('policy_token')){storeAuth(await call('/api/v1/auth/guest','POST'));return true}return false}
export async function loginWechat(bindGuest=false){
 // #ifdef MP-WEIXIN
 const code=await new Promise<string>((resolve,reject)=>uni.login({provider:'weixin',success:r=>r.code?resolve(r.code):reject(new Error('未取得微信登录凭证')),fail:()=>reject(new Error('微信登录未完成'))}))
 const r=await call('/api/v1/auth/wechat','POST',{code,bind_guest:bindGuest});storeAuth(r);return r
 // #endif
 // #ifndef MP-WEIXIN
 throw new Error('请在微信小程序中使用微信登录。')
 // #endif
}
export const uid=()=>Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,12)
export const delay=(ms:number)=>new Promise(r=>setTimeout(r,ms))
