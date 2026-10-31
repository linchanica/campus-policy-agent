# 微信模拟器联调

此工具连接微信开发者工具中的本项目，使用真实平台API，不模拟登录。它执行本机健康请求、wx.login/服务端交换、标注为虚构资料的咨询、登记表下载及哈希检查、学生访问管理接口的拒绝检查。

凭证只在模拟器和本机后端之间使用，不输出到报告。会在本人微信身份下建立一条开发联调会话；不迁移访客历史、不提交人工工单、不上传或发布代码。登录不代表学校身份验证。

在开发工具已登录、本机后端运行、服务端微信配置就绪的环境执行：

1. 本人开启开发工具服务端口。
2. 在本目录执行 `pnpm install --frozen-lockfile --ignore-scripts`，SDK固定为0.13.0。
3. 使用官方CLI打开项目并指定本机自动化端口：

   ```powershell
   & 'C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat' auto --project '<本项目绝对路径>/frontend/student/dist/build/mp-weixin' --auto-port 9420
   ```

4. 执行 `pnpm run verify`。报告位于 `docs/verification/wechat_integration.json`。

原生WXML/WXSS语法检查独立执行：

```powershell
.venv/Scripts/python.exe scripts/verify_wechat_compilers.py --devtools-dir 'C:/Program Files (x86)/Tencent/微信web开发者工具'
```

本次曾出现 `app.wxss unexpected token *`，已从App.vue移除通配选择器并保留显式组件的盒模型设置。官方模板和样式编译均已通过。开发工具卡住后曾使用官方 `--disable-gpu` 参数重新启动，并成功恢复模拟器；不能据此认定图形驱动是唯一原因。

模拟器链路通过不代表按钮自动化、手机真机、文件预览、跨端绑定、体验版或平台审核已通过。自动化的元素选择接口在此环境出现等待，因此本次原生平台API测试与界面显示分别记录。
