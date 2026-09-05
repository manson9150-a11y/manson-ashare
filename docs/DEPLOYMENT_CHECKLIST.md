# MANSON 上线记录与配置说明

2026-09-06 已完成公开仓库发布、Actions 权限、Pages 托管、Google Docs API 和指定文档服务账号共享；两个认证参数已保存至 GitHub Secrets。

- 正式网站：https://manson9150-a11y.github.io/manson-ashare/
- 云端测试通过：https://github.com/manson9150-a11y/manson-ashare/actions/runs/33977922175
- 生产流程通过：https://github.com/manson9150-a11y/manson-ashare/actions/runs/33977954538
- 云端文档读写通过：https://github.com/manson9150-a11y/manson-ashare/actions/runs/33978018833

生产运行正确记录 `NON_TRADING_DAY`，自动提交状态并部署网站。Google 验证只写入一段系统测试标记，重复执行不重复追加，不生成模拟行情报告。

首个正式收盘扫描预计在 2026-09-07 16:00（北京时间）触发。首轮盘前和午盘可能因缺少前序正式快照而停止，这是时间链约束；收盘扫描会建立基础，晚间及次日阶段继续衔接。GitHub 定时任务可能延迟，实际完成时间以 Actions 为准。交易日行情覆盖、运行耗时和正式报告五阶段闭环仍需届时验收。

后续可在 Actions → Verify Google Docs connection → Run workflow 重复检查认证和读写能力。

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

以上设置已完成；下方步骤保留供迁移或重建环境时使用。交易日数据与完整闭环验证不由休市部署验证代替。
