const automator=require('miniprogram-automator');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..');
let mini,phase='connect';
const report={status:'running',real_platform_apis:true,mocked_login:false,simulator_only:true,device_tested:false,ui_button_path_tested:false};
const timer=setTimeout(()=>{console.log(JSON.stringify({...report,status:'timeout',phase}));process.exit(2)},90000);
const stage=s=>{phase=s;console.log(s)};
const ensure=(value,message)=>{if(!value)throw new Error(message)};
(async()=>{
 mini=await automator.connect({wsEndpoint:'ws://127.0.0.1:9420'});
 stage('runtime_state');
 const state=await mini.evaluate(()=>({appid:wx.getAccountInfoSync().miniProgram.appId,page_count:getCurrentPages().length,has_guest_token:!!wx.getStorageSync('policy_token')}));
 ensure(state.appid==='wx819a8152776e26fa','Simulator AppID mismatch');report.page_created=state.page_count>0;
 const request=async(url,method='GET',data,token)=>{
  const result=await mini.callWxMethod('request',{url:'http://127.0.0.1:8000'+url,method,data,timeout:20000,header:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})}});
  return {status:result.statusCode,data:result.data};
 };
 stage('native_request');
 const health=await request('/health/ready');ensure(health.status===200&&health.data.status==='ready','Native wx.request cannot reach backend');report.native_network_connected=true;
 stage('real_wx_login');
 const login=await mini.callWxMethod('login');ensure(typeof login.code==='string'&&login.code.length>0,'No real login code');
 const auth=await request('/api/v1/auth/wechat','POST',{code:login.code,bind_guest:false});
 report.wechat_login={http_status:auth.status,passed:auth.status===200&&auth.data.auth_mode==='wechat'};
 if(!report.wechat_login.passed){report.wechat_login.error_code=auth.data?.detail?.code||null;report.wechat_login.message=auth.data?.detail?.message||'登录交换未成功';throw new Error('Real WeChat server exchange did not pass');}
 const token=auth.data.access_token;
 await mini.evaluate((r)=>{wx.setStorageSync('policy_token',r.access_token);wx.setStorageSync('policy_token_expires',r.expires_at);wx.setStorageSync('policy_auth_mode',r.auth_mode)},auth.data);
 const me=await request('/api/v1/auth/me','GET',undefined,token);ensure(me.status===200&&me.data.auth_mode==='wechat','Verified login mode was not retained');
 report.wechat_login.school_identity_verified=me.data.verified_staff;report.wechat_login.role=me.data.role;
 stage('fictional_policy_consultation');
 const session=await request('/api/v1/sessions','POST',{topic:'midterm'},token);ensure(session.status===200,'Cannot create own session');
 const turn=await request('/api/v1/sessions/'+session.data.session_id+'/messages','POST',{text:'【开发联调，虚构资料】我是人工智能学院2025级学术学位硕士，中期考核登记表在哪里下载？',client_message_id:'wx-qa-'+Date.now(),expected_profile_revision:0,channel:'mp_weixin'},token);
 ensure(turn.status===202,'Cannot submit own question');
 let result;
 for(let i=0;i<45;i++){
  const current=await request('/api/v1/turns/'+turn.data.turn_id,'GET',undefined,token);
  if(current.data.state==='COMPLETED'){result=current.data.result;break}
  if(['FAILED','STALE'].includes(current.data.state))throw new Error('Consultation did not complete');
  await new Promise(r=>setTimeout(r,700));
 }
 ensure(result&&result.validation.source_ids_valid,'No grounded consultation result');
 report.consultation={fictional_input:true,decision:result.decision,source_ids_valid:result.validation.source_ids_valid,policy_keys:[...new Set(result.sources.map(s=>s.policy_key))],materials_have_registration_form:result.materials.some(m=>m.attachment_key==='p033'),generation_mode:result.generation_mode};
 stage('native_attachment_download');
 const material=result.materials.find(m=>m.attachment_key==='p033');ensure(material,'Registration form attachment missing');
 const downloaded=await mini.callWxMethod('downloadFile',{url:'http://127.0.0.1:8000/api/v1/attachments/p033?version='+encodeURIComponent(material.attachment_version||'current'),header:{Authorization:'Bearer '+token}});
 ensure(downloaded.statusCode===200,'Native file download failed');
 const base64=await mini.evaluate((p)=>wx.getFileSystemManager().readFileSync(p,'base64'),downloaded.tempFilePath);
 const bytes=Buffer.from(base64,'base64');
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'data/manifests/policies.json'),'utf8'));
 const expected=manifest.files.find(p=>p.key==='p033').sha256;
 report.attachment={download_status:downloaded.statusCode,bytes:bytes.length,sha256_matches_original:crypto.createHash('sha256').update(bytes).digest('hex')===expected};
 ensure(report.attachment.sha256_matches_original,'Downloaded file hash differs from the original');
 const denied=await request('/api/v1/admin/workspace','GET',undefined,token);report.student_admin_access_denied=denied.status===403;ensure(report.student_admin_access_denied,'Student unexpectedly has admin access');
 stage('refresh_own_page');
 await mini.callWxMethod('reLaunch',{url:'/pages/index/index'});
 report.status='pass';report.completed_at=new Date().toISOString();
})().catch(e=>{report.status='failed';report.phase=phase;report.message=String(e.message).slice(0,300);process.exitCode=1}).finally(async()=>{
 clearTimeout(timer);
 fs.writeFileSync(path.join(root,'docs/verification/wechat_integration.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(report));
 if(mini)await mini.disconnect();
});
