# MANSON最终上线两步

## 1. GitHub

- 登录GitHub Desktop，把 `manson-ashare` 本地仓库发布到自己的GitHub账号，分支main。
- 公共仓库会公开因子、候选和研究报告；选择符合自己隐私偏好的可见性。
- Settings → Actions → General → Workflow permissions：Read and write。
- Settings → Pages → Source：GitHub Actions。
- Actions → Publish Dashboard → Run workflow，完成后使用Pages显示的正式地址。
- 查看Tests工作流通过，从下一个交易日16:00开始建立正式闭环。

## 2. Google Docs

- 创建Google服务账号并启用Google Docs API。
- 将现有研究主文档共享给服务账号邮箱，编辑权限。
- GitHub Secrets设置 `GOOGLE_DOC_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`。
- 下一次成功研究任务会重试待补传报告。

无需购买行情API、租服务器，也无需填写OPENAI_API_KEY。当前本机预览地址只用于验收，不能代替上述正式托管。

授权设置完成后，还需要在GitHub实际跑通一次生产任务和Google写入，才能将部署验收标记为完成。
