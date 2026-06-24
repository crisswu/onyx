"use client";

import { useEffect } from "react";

const TEXT_TRANSLATIONS = new Map<string, string>([
  ["Question answering for your documents", "面向企业文档的智能问答"],
  ["Welcome to", "欢迎使用"],
  ["Welcome to Onyx", "欢迎使用 Onyx"],
  ["Welcome to Onyx!", "欢迎使用 Onyx！"],
  ["Your open source AI platform for work", "面向工作的开源 AI 平台"],
  ["New Session", "新会话"],
  ["New Chat", "新聊天"],
  ["Recents", "最近"],
  [
    "Try sending a message! Your chat history will appear here.",
    "试着发送一条消息，你的聊天历史会显示在这里。",
  ],
  ["Craft", "构建"],
  ["Search", "搜索"],
  ["Search Chats", "搜索聊天"],
  ["Search...", "搜索..."],
  ["Search chat sessions, projects...", "搜索聊天会话、项目..."],
  ["Search Projects", "搜索项目"],
  ["Search Connectors", "搜索连接器"],
  ["Search tools…", "搜索工具..."],
  ["Search tools", "搜索工具"],
  ["Search service accounts...", "搜索服务账号..."],
  ["Search hooks...", "搜索 Hook..."],
  ["Search for an agent...", "搜索智能体..."],
  ["Search for connectors...", "搜索连接器..."],
  ["Search for federated connectors...", "搜索联合连接器..."],
  ["Search files...", "搜索文件..."],
  ["Search models...", "搜索模型..."],
  ["Search actions...", "搜索操作..."],
  ["Filter actions...", "筛选操作..."],
  ["Created by...", "创建者..."],
  ["Open chat search", "打开聊天搜索"],
  ["Change app mode", "切换应用模式"],
  ["Select", "选择"],
  ["Select strategy", "选择策略"],
  ["Select method", "选择方法"],
  ["Select mode", "选择模式"],
  ["Select permissions", "选择权限"],
  ["Select access level", "选择访问级别"],
  ["Select a region", "选择区域"],
  ["Select...", "选择..."],
  ["Show all", "显示全部"],
  ["Show all tools", "显示全部工具"],
  ["Show only enabled", "仅显示已启用"],
  ["Show only enabled tools", "仅显示已启用工具"],
  ["Open", "打开"],
  ["Sessions", "会话"],
  ["Projects", "项目"],
  ["Project", "项目"],
  ["Create Project", "创建项目"],
  ["New Project", "新建项目"],
  ["Move to Project", "移动到项目"],
  ["Create New Project", "创建新项目"],
  ["Explore Agents", "探索智能体"],
  ["More Agents", "更多智能体"],
  ["Curator Panel", "内容管理员面板"],
  ["Settings", "设置"],
  ["Notifications", "通知"],
  ["Help & FAQ", "帮助与常见问题"],
  ["Log in", "登录"],
  ["Log In", "登录"],
  ["Log Out", "退出登录"],
  ["Exit Admin Panel", "退出管理面板"],
  ["Admin Panel", "管理面板"],
  ["Admin Page", "管理页面"],
  ["Curator Page", "内容管理员页面"],
  ["Upgrade Plan", "升级方案"],
  ["Plans", "方案"],
  ["Billing", "账单"],
  ["Agents & Actions", "智能体与操作"],
  ["Documents & Knowledge", "文档与知识"],
  ["Integrations", "集成"],
  ["Permissions", "权限"],
  ["Organization", "组织"],
  ["Usage", "使用情况"],
  ["Existing Connectors", "现有连接器"],
  ["Add Connector", "添加连接器"],
  ["Document Sets", "文档集"],
  ["Document Explorer", "文档浏览器"],
  ["Explorer", "浏览器"],
  ["Document Feedback", "文档反馈"],
  ["Feedback", "反馈"],
  ["Agents", "智能体"],
  ["Agent", "智能体"],
  ["Slack Integration", "Slack 集成"],
  ["Discord Integration", "Discord 集成"],
  ["MCP Actions", "MCP 操作"],
  ["OpenAPI Actions", "OpenAPI 操作"],
  ["Standard Answers", "标准答案"],
  ["Manage User Groups", "管理用户组"],
  ["Groups", "用户组"],
  ["Chat Preferences", "聊天偏好"],
  ["Language Models", "语言模型"],
  ["Web Search", "网页搜索"],
  ["Image Generation", "图像生成"],
  ["Voice", "语音"],
  ["Code Interpreter", "代码解释器"],
  ["Index Settings", "索引设置"],
  ["Document Processing", "文档处理"],
  ["Users & Requests", "用户与请求"],
  ["Users", "用户"],
  ["Service Accounts", "服务账号"],
  ["Spending Limits", "支出限制"],
  ["Usage Statistics", "使用统计"],
  ["Query History", "查询历史"],
  ["Custom Analytics", "自定义分析"],
  ["Appearance & Theming", "外观与主题"],
  ["Plans & Billing", "方案与账单"],
  ["Hook Extensions", "Hook 扩展"],
  ["Debug Logs", "调试日志"],
  ["Security & Hardening", "安全与加固"],
  ["SCIM", "SCIM"],
  ["System Info", "系统信息"],
  ["Sign In", "登录"],
  ["Sign in", "登录"],
  ["Sign Up", "注册"],
  ["Sign up", "注册"],
  ["Complete your sign up", "完成注册"],
  ["Create account", "创建账号"],
  ["Get started with Onyx", "开始使用 Onyx"],
  ["Reset Password", "重置密码"],
  ["Forgot Password", "忘记密码"],
  ["Back to Login", "返回登录"],
  ["Forgot password?", "忘记密码？"],
  ["Don't have an account?", "还没有账号？"],
  ["Already have an account?", "已有账号？"],
  ["Create an account", "创建账号"],
  ["Create Account", "创建账号"],
  ["or continue as guest", "或以访客身份继续"],
  ["Email", "邮箱"],
  ["Email Address", "邮箱地址"],
  ["Your name", "你的姓名"],
  ["Password", "密码"],
  ["New Password", "新密码"],
  ["Confirm New Password", "确认新密码"],
  ["Enter your new password", "输入新密码"],
  ["Confirm your new password", "确认你的新密码"],
  ["Password is required", "请输入密码"],
  ["Passwords must match", "两次输入的密码必须一致"],
  ["Confirm Password is required", "请确认密码"],
  ["First Name", "名字"],
  ["Last Name", "姓氏"],
  ["Company", "公司"],
  ["Role", "角色"],
  ["Invite Code", "邀请码"],
  ["Display Name", "显示名称"],
  ["Display name", "显示名称"],
  ["Model name", "模型名称"],
  ["Enter model name", "输入模型名称"],
  ["Input type", "输入类型"],
  ["Default", "默认"],
  ["API Key", "API 密钥"],
  ["Your long-term API key", "你的长期 API 密钥"],
  ["Invalid or missing reset token.", "重置令牌无效或缺失。"],
  [
    "Password reset email sent. Please check your inbox.",
    "密码重置邮件已发送，请检查你的收件箱。",
  ],
  [
    "Password reset successfully. Redirecting to login...",
    "密码重置成功，正在跳转到登录页...",
  ],
  ["An error occurred. Please try again.", "发生错误，请重试。"],
  ["An error occurred during password reset.", "重置密码时发生错误。"],
  ["An unexpected error occurred. Please try again.", "发生意外错误，请重试。"],
  ["Join", "加入"],
  ["Joining...", "正在加入..."],
  ["Creating account...", "正在创建账号..."],
  ["Signing in...", "正在登录..."],
  ["Signing out...", "正在退出登录..."],
  ["Account created. Signing in...", "账号已创建，正在登录..."],
  ["Signed in successfully.", "登录成功。"],
  ["Account created successfully. Please log in.", "账号创建成功，请登录。"],
  ["Unknown error", "未知错误"],
  ["Invalid email or password", "邮箱或密码无效"],
  ["Create an account to set a password", "创建账号以设置密码"],
  ["Too many requests. Please try again later.", "请求过多，请稍后重试。"],
  ["An account already exists with the specified email.", "该邮箱已存在账号。"],
  [
    "Your email has been verified! Please sign in to continue.",
    "你的邮箱已验证，请登录继续。",
  ],
  ["or", "或"],
  ["Loading", "加载中"],
  ["Loading...", "加载中..."],
  ["Loading more...", "正在加载更多..."],
  ["Saving...", "正在保存..."],
  ["Adding...", "正在添加..."],
  ["Connecting...", "正在连接..."],
  ["Uploading...", "正在上传..."],
  ["Processing...", "处理中..."],
  ["Fetching tools...", "正在获取工具..."],
  ["Thinking", "思考中"],
  ["How can I help you today?", "今天我可以帮你做什么？"],
  ["Ask anything", "询问任何问题"],
  ["Message", "消息"],
  ["Save", "保存"],
  ["Saved", "已保存"],
  ["Save Changes", "保存更改"],
  ["Cancel", "取消"],
  ["Close", "关闭"],
  ["Done", "完成"],
  ["Create", "创建"],
  ["Update", "更新"],
  ["Edit", "编辑"],
  ["Delete", "删除"],
  ["Remove", "移除"],
  ["Add", "添加"],
  ["Continue", "继续"],
  ["Back", "返回"],
  ["Next", "下一步"],
  ["Previous", "上一步"],
  ["Submit", "提交"],
  ["Confirm", "确认"],
  ["Retry", "重试"],
  ["Refresh", "刷新"],
  ["Refresh tools", "刷新工具"],
  ["Copy", "复制"],
  ["Copied", "已复制"],
  ["Copy redirect URI", "复制重定向 URI"],
  ["Copy definition", "复制定义"],
  ["Format definition", "格式化定义"],
  ["Download", "下载"],
  ["Upload", "上传"],
  ["Import", "导入"],
  ["Export", "导出"],
  ["Enable", "启用"],
  ["Disable", "停用"],
  ["Enabled", "已启用"],
  ["Disabled", "已停用"],
  ["Active", "活跃"],
  ["Inactive", "未活跃"],
  ["Connected", "已连接"],
  ["Disconnected", "已断开"],
  ["Connect", "连接"],
  ["Disconnect", "断开连接"],
  ["Reconnect", "重新连接"],
  ["Authenticate", "认证"],
  ["Public", "公开"],
  ["Private", "私有"],
  ["Success", "成功"],
  ["Error", "错误"],
  ["Warning", "警告"],
  ["Info", "信息"],
  ["Failed", "失败"],
  ["Completed", "已完成"],
  ["Completed with errors", "已完成但有错误"],
  ["Succeeded", "已成功"],
  ["Pending", "等待中"],
  ["Running", "运行中"],
  ["Queued", "排队中"],
  ["Skipped", "已跳过"],
  ["Scheduled", "已计划"],
  ["Canceled", "已取消"],
  ["Not Started", "未开始"],
  ["In Progress", "进行中"],
  ["Up to Date", "已是最新"],
  ["Out of Date", "已过期"],
  ["Never", "从未"],
  ["Unknown", "未知"],
  ["Name", "名称"],
  ["Description", "描述"],
  ["Status", "状态"],
  ["Type", "类型"],
  ["Owner", "所有者"],
  ["Date", "日期"],
  ["Time", "时间"],
  ["Time Started", "开始时间"],
  ["Time Updated", "更新时间"],
  ["Last Updated", "最后更新"],
  ["Last Successful Index", "上次成功索引"],
  ["Last Attempt", "上次尝试"],
  ["Next Run", "下次运行"],
  ["Created", "已创建"],
  ["Updated", "已更新"],
  ["Actions", "操作"],
  ["Details", "详情"],
  ["Overview", "概览"],
  ["General", "通用"],
  ["Advanced", "高级"],
  ["Configure", "配置"],
  ["Manage", "管理"],
  ["Accounts & Access", "账号与访问"],
  ["Connectors", "连接器"],
  ["Connector", "连接器"],
  ["Connector Name", "连接器名称"],
  ["Document Access", "文档访问"],
  ["Federated Connectors", "联合连接器"],
  ["Regular Connectors", "普通连接器"],
  ["Documents", "文档"],
  ["Document", "文档"],
  ["Document Name", "文档名称"],
  ["Document Set", "文档集"],
  ["New Document Set", "新建文档集"],
  ["Edit Document Set", "编辑文档集"],
  ["Create Document Set", "创建文档集"],
  ["Update Document Set", "更新文档集"],
  ["Failed to fetch Connectors", "获取连接器失败"],
  ["Document set not found", "未找到文档集"],
  ["Knowledge", "知识"],
  ["All Public Knowledge", "全部公开知识"],
  ["Specific Document Sets", "指定文档集"],
  ["No results found", "未找到结果"],
  ["No Results", "无结果"],
  ["No data", "无数据"],
  ["No Knowledge", "无知识库"],
  ["No tools available", "没有可用工具"],
  ["No tools found", "未找到工具"],
  ["No Actions Found", "未找到操作"],
  ["No summary provided", "未提供摘要"],
  [
    "No credential schema available for this connector type.",
    "此连接器类型没有可用的凭证架构。",
  ],
  [
    "No search configuration available for this connector type.",
    "此连接器类型没有可用的搜索配置。",
  ],
  ["Found Sources", "找到的来源"],
  ["Source", "来源"],
  ["More", "更多"],
  ["Sources", "来源"],
  ["Files", "文件"],
  ["File", "文件"],
  ["Uploaded image", "已上传图片"],
  ["Chat Message Image", "聊天消息图片"],
  ["Folders", "文件夹"],
  ["Folder", "文件夹"],
  ["Selected File", "已选择文件"],
  ["Selected Files", "已选择文件"],
  ["Documents Indexed", "已索引文档"],
  ["Knowledge Cutoff Date", "知识截止日期"],
  ["We encountered an issue", "遇到问题"],
  ["Share", "分享"],
  ["share-chat-button", "分享聊天按钮"],
  ["Rename", "重命名"],
  ["Delete Chat", "删除聊天"],
  [
    "Are you sure you want to delete this chat? This action cannot be undone.",
    "确定要删除此聊天吗？此操作无法撤销。",
  ],
  ["Quick search for documents", "快速搜索文档"],
  ["Conversation and research", "对话与研究"],
  ["Chat", "聊天"],
  [
    "Chat with an agent that does not use documents",
    "与不使用文档的智能体聊天",
  ],
  ["Search Agent", "搜索智能体"],
  ["Non-Search Agent", "非搜索智能体"],
  ["Search Configuration", "搜索配置"],
  [
    "Use pass-through for services with shared identity provider.",
    "对共享身份提供商的服务使用透传。",
  ],
  [
    "Onyx will forward the user's OAuth access token directly to the server as an Authorization header. Make sure the server supports authentication with the same provider.",
    "Onyx 会将用户的 OAuth 访问令牌作为 Authorization 头直接转发到服务器。请确保服务器支持同一提供商的认证。",
  ],
  ["Authentication Method", "认证方式"],
  ["Authorization URL", "授权 URL"],
  ["Token URL", "令牌 URL"],
  ["OAuth Client ID", "OAuth 客户端 ID"],
  ["OAuth Client Secret", "OAuth 客户端密钥"],
  ["Header", "请求头"],
  ["Value", "值"],
  ["Add Header", "添加请求头"],
  ["Name your MCP server", "为 MCP 服务器命名"],
  ["More details about the MCP server", "MCP 服务器的更多详情"],
  ["Shared API key for your organization", "组织共享 API 密钥"],
  ["OpenAPI Schema Definition", "OpenAPI 架构定义"],
  ["Add OpenAPI action", "添加 OpenAPI 操作"],
  ["Edit OpenAPI action", "编辑 OpenAPI 操作"],
  ["Add Action", "添加操作"],
  ["Update the OpenAPI schema for this action.", "更新此操作的 OpenAPI 架构。"],
  [
    "Add OpenAPI schema to add custom actions.",
    "添加 OpenAPI 架构以添加自定义操作。",
  ],
  ["Enter your OpenAPI schema here", "在此输入 OpenAPI 架构"],
  [
    "Provide OpenAPI schema to preview actions here.",
    "提供 OpenAPI 架构以在此预览操作。",
  ],
  ["Authenticated & Enabled", "已认证并启用"],
  ["Authentication configured", "认证已配置"],
  ["OAuth authentication configured", "OAuth 认证已配置"],
  ["Custom authentication headers configured", "自定义认证请求头已配置"],
  ["Passthrough authentication enabled", "透传认证已启用"],
  ["Disable action", "停用操作"],
  ["Delete MCP server", "删除 MCP 服务器"],
  ["Delete Server", "删除服务器"],
  ["Disconnect Server", "断开服务器连接"],
  ["Manage Server", "管理服务器"],
  ["Current Default", "当前默认"],
  ["Set as Default", "设为默认"],
  ["Update Service Account", "更新服务账号"],
  ["Create Service Account", "创建服务账号"],
  ["Delete Account", "删除账号"],
  ["Successfully updated service account!", "服务账号更新成功！"],
  ["Successfully created service account!", "服务账号创建成功！"],
  ["Failed to load service accounts.", "加载服务账号失败。"],
  [
    "Create service account API keys with user-level access.",
    "创建具有用户级访问权限的服务账号 API 密钥。",
  ],
  [
    "Save this key before continuing. It won't be shown again.",
    "继续前请保存此密钥。它不会再次显示。",
  ],
  ["Built-in", "内置"],
  ["Custom", "自定义"],
  ["Unavailable", "不可用"],
  ["You Have Been Logged Out", "你已退出登录"],
  ["The backend is currently unavailable", "后端当前不可用"],
  [
    "If this is your initial setup or you just updated your Onyx deployment, this is likely because the backend is still starting up. Give it a minute or two, and then refresh the page. If that does not work, make sure the backend is setup and/or contact an administrator.",
    "如果这是首次设置，或你刚更新了 Onyx 部署，后端可能仍在启动。请等待一两分钟后刷新页面。如果仍然无效，请确认后端已正确配置，或联系管理员。",
  ],
  ["Indexing", "索引"],
  ["Document Permissions", "文档权限"],
  ["Group Membership", "组成员关系"],
  ["Failed to load sync attempts", "加载同步尝试失败"],
  ["Not applicable", "不适用"],
  ["No group membership sync attempts yet", "还没有组成员关系同步尝试"],
  [
    "Group-membership sync runs are scheduled in the background. They may take some time to appear — try refreshing in ~30 seconds.",
    "组成员关系同步会在后台计划运行，可能需要一些时间才会显示。请约 30 秒后刷新。",
  ],
  ["Stage", "阶段"],
  ["Avg time", "平均时间"],
  ["Total time", "总时间"],
  ["Calls", "调用次数"],
  ["Min", "最小值"],
  ["Max", "最大值"],
  ["Failed to load stage metrics", "加载阶段指标失败"],
  [
    "Stage timing data could not be loaded for this attempt. The pipeline runs even when metric recording is unavailable, so this does not indicate a problem with the indexing run itself.",
    "无法加载此次尝试的阶段耗时数据。即使指标记录不可用，流水线也会继续运行，因此这不代表索引运行本身有问题。",
  ],
  ["Show attempt overhead", "显示尝试开销"],
  ["Hide attempt overhead", "隐藏尝试开销"],
  ["Group Membership Sync Error", "组成员关系同步错误"],
  ["Error Message", "错误消息"],
  ["View full error message", "查看完整错误消息"],
  ["View full trace", "查看完整跟踪"],
  ["View stage metrics", "查看阶段指标"],
  [
    "Total number of documents replaced in the index during this indexing attempt",
    "此次索引尝试中在索引内被替换的文档总数",
  ],
  [
    "This feature is available on the Enterprise version of Onyx only.",
    "此功能仅在 Onyx 企业版中可用。",
  ],
  [
    "This feature is available on the Business or Enterprise version of Onyx only.",
    "此功能仅在 Onyx 商业版或企业版中可用。",
  ],
  ["Failed to logout", "退出登录失败"],
  ["Failed to delete chat. Please try again.", "删除聊天失败，请重试。"],
  ["Failed to move chat. Please try again.", "移动聊天失败，请重试。"],
  ["Failed to create project. Please try again.", "创建项目失败，请重试。"],
  ["An unexpected error occurred.", "发生意外错误。"],
  ["Invalid JSON format", "JSON 格式无效"],
  [
    "Invalid JSON format in OpenAPI schema definition",
    "OpenAPI 架构定义中的 JSON 格式无效",
  ],
  ["OpenAPI action updated successfully", "OpenAPI 操作更新成功"],
  ["OpenAPI action created successfully", "OpenAPI 操作创建成功"],
  ["Failed to update OpenAPI action", "更新 OpenAPI 操作失败"],
  ["Failed to create OpenAPI action", "创建 OpenAPI 操作失败"],
  ["Transport is required", "传输方式为必填项"],
  ["Authentication type is required", "认证类型为必填项"],
  ["Authentication method is required", "认证方式为必填项"],
  ["Enter a valid URL", "请输入有效 URL"],
  ["Authorization URL is required", "授权 URL 为必填项"],
  ["Token URL is required", "令牌 URL 为必填项"],
  ["Client ID is required", "客户端 ID 为必填项"],
  ["Client secret is required", "客户端密钥为必填项"],
  ["Header key is required", "请求头键为必填项"],
  ["Header value is required", "请求头值为必填项"],
  ["Add at least one authentication header", "请至少添加一个认证请求头"],
  ["OpenAPI schema definition is required", "OpenAPI 架构定义为必填项"],
]);

const PATTERN_TRANSLATIONS: Array<
  [RegExp, (match: RegExpExecArray) => string]
> = [
  [
    /^Password must be at least (\d+) characters$/,
    (match) => `密码长度至少为 ${capture(match)} 个字符`,
  ],
  [
    /^Enter your (.+)$/,
    (match) => `输入你的 ${translateCapturedText(capture(match))}`,
  ],
  [/^Enter (.+)$/, (match) => `输入 ${translateCapturedText(capture(match))}`],
  [
    /^Failed to sign up - (.+)$/,
    (match) => `注册失败 - ${translateCapturedText(capture(match))}`,
  ],
  [
    /^Failed to login - (.+)$/,
    (match) => `登录失败 - ${translateCapturedText(capture(match))}`,
  ],
  [
    /^Remove from (.+)$/,
    (match) => `从 ${translateCapturedText(capture(match))} 中移除`,
  ],
  [/^Create (.+)$/, (match) => `创建 ${translateCapturedText(capture(match))}`],
  [
    /^Rename (.+)$/,
    (match) => `重命名 ${translateCapturedText(capture(match))}`,
  ],
  [/^Delete (.+)$/, (match) => `删除 ${translateCapturedText(capture(match))}`],
  [/^Edit (.+)$/, (match) => `编辑 ${translateCapturedText(capture(match))}`],
  [/^Manage (.+)$/, (match) => `管理 ${translateCapturedText(capture(match))}`],
  [
    /^Disconnect (.+)$/,
    (match) => `断开 ${translateCapturedText(capture(match))}`,
  ],
  [
    /^Reconnect to (.+)$/,
    (match) => `重新连接到 ${translateCapturedText(capture(match))}`,
  ],
  [/^View (\d+) tools?$/, (match) => `查看 ${capture(match)} 个工具`],
  [
    /^View tools for (.+)$/,
    (match) => `查看 ${translateCapturedText(capture(match))} 的工具`,
  ],
  [
    /^Authenticate and connect to (.+)$/,
    (match) => `认证并连接到 ${translateCapturedText(capture(match))}`,
  ],
  [
    /^Unavailable — (.+)$/,
    (match) => `不可用 - ${translateCapturedText(capture(match))}`,
  ],
  [
    /^OAuth connected via (.+)$/,
    (match) => `已通过 ${translateCapturedText(capture(match))} 连接 OAuth`,
  ],
  [
    /^Document set with id (.+) not found$/,
    (match) => `未找到 ID 为 ${capture(match)} 的文档集`,
  ],
  [
    /^Failed to update role: (.+)$/,
    (match) => `更新角色失败：${translateCapturedText(capture(match))}`,
  ],
  [
    /^Failed to regenerate API Key: (.+)$/,
    (match) =>
      `重新生成 API 密钥失败：${translateCapturedText(capture(match))}`,
  ],
  [
    /^Failed to delete API Key: (.+)$/,
    (match) => `删除 API 密钥失败：${translateCapturedText(capture(match))}`,
  ],
  [
    /^Error updating service account - (.+)$/,
    (match) => `更新服务账号出错 - ${translateCapturedText(capture(match))}`,
  ],
  [
    /^Error creating service account - (.+)$/,
    (match) => `创建服务账号出错 - ${translateCapturedText(capture(match))}`,
  ],
  [/^less than a minute ago$/, () => "不到 1 分钟前"],
  [/^(\d+) seconds? ago$/, (match) => `${capture(match)} 秒前`],
  [/^(\d+) minutes? ago$/, (match) => `${capture(match)} 分钟前`],
  [/^(\d+) hours? ago$/, (match) => `${capture(match)} 小时前`],
  [/^(\d+) days? ago$/, (match) => `${capture(match)} 天前`],
  [/^(\d+) weeks? ago$/, (match) => `${capture(match)} 周前`],
  [/^(\d+) months? ago$/, (match) => `${capture(match)} 个月前`],
  [/^(\d+) years? ago$/, (match) => `${capture(match)} 年前`],
];

const ATTRIBUTE_NAMES = [
  "aria-label",
  "aria-placeholder",
  "data-placeholder",
  "title",
  "placeholder",
  "alt",
] as const;
const SKIP_SELECTORS = [
  "script",
  "style",
  "noscript",
  "code",
  "pre",
  "kbd",
  "samp",
  "textarea",
  ".prose",
  "#onyx-human-message",
  "[data-testid='onyx-ai-message']",
  "[contenteditable='true']",
  "[data-no-localize]",
] as const;
const SKIP_SELECTOR = SKIP_SELECTORS.join(",");

function capture(match: RegExpExecArray, index = 1): string {
  return match[index] ?? "";
}

function translateCapturedText(value: string): string {
  return getTranslation(value) ?? value;
}

function getTranslation(value: string): string | null {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;

  const exact = TEXT_TRANSLATIONS.get(normalized);
  if (exact) return exact;

  for (const [pattern, translate] of PATTERN_TRANSLATIONS) {
    const match = pattern.exec(normalized);
    if (match) return translate(match);
  }

  return null;
}

function translatePreservingOuterWhitespace(value: string): string | null {
  const translation = getTranslation(value);
  if (!translation) return null;

  const leading = value.match(/^\s*/)?.[0] ?? "";
  const trailing = value.match(/\s*$/)?.[0] ?? "";
  return `${leading}${translation}${trailing}`;
}

function shouldSkipElement(element: Element | null): boolean {
  return Boolean(element?.closest(SKIP_SELECTOR));
}

function translateTextNode(node: Text): void {
  if (shouldSkipElement(node.parentElement)) return;

  const translated = translatePreservingOuterWhitespace(node.data);
  if (translated && translated !== node.data) {
    node.data = translated;
  }
}

function translateElementAttributes(element: Element): void {
  if (
    shouldSkipElement(element) &&
    !element.matches("[contenteditable='true']")
  ) {
    return;
  }

  for (const attributeName of ATTRIBUTE_NAMES) {
    const value = element.getAttribute(attributeName);
    if (!value) continue;

    const translated = getTranslation(value);
    if (translated && translated !== value) {
      element.setAttribute(attributeName, translated);
    }
  }
}

function translateTree(root: Node): void {
  if (root.nodeType === Node.TEXT_NODE) {
    translateTextNode(root as Text);
    return;
  }

  if (
    root.nodeType !== Node.ELEMENT_NODE &&
    root.nodeType !== Node.DOCUMENT_NODE
  ) {
    return;
  }

  if (root.nodeType === Node.ELEMENT_NODE) {
    const element = root as Element;
    translateElementAttributes(element);
    if (shouldSkipElement(element)) return;
  }

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let current = walker.nextNode();
  while (current) {
    translateTextNode(current as Text);
    current = walker.nextNode();
  }

  if (root.nodeType === Node.ELEMENT_NODE) {
    (root as Element)
      .querySelectorAll("*")
      .forEach((element) => translateElementAttributes(element));
  }
}

export default function ChineseLocalizationProvider() {
  useEffect(() => {
    const body = document.body;
    translateTree(body);

    let frame: number | null = null;
    const scheduleTranslate = () => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        translateTree(body);
      });
    };

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          translateTree(mutation.target);
          continue;
        }

        if (mutation.type === "attributes") {
          translateTree(mutation.target);
          continue;
        }

        if (mutation.addedNodes.length > 0) {
          scheduleTranslate();
        }
      }
    });

    observer.observe(body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...ATTRIBUTE_NAMES],
    });

    return () => {
      observer.disconnect();
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
      }
    };
  }, []);

  return null;
}
