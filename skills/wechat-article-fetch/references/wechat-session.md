# 微信会话凭证：为什么需要，怎么拿

## 为什么正文不需要登录、留言却需要

- 文章正文页 `mp.weixin.qq.com/s/...` 是公开页面，未登录浏览器也能看到正文（`#js_content`），
  所以正文靠 HTTP 直连 + 浏览器兜底就够。
- 留言走独立接口 `/mp/appmsg_comment?action=getcomment`，服务端按会话鉴权。
  匿名请求的返回固定是：

  ```json
  {"base_resp":{"ret":-3,"errmsg":"no session","cookie_count":0},"ret":-3}
  ```

  这时文章 HTML 里仍有 `comment_id`，但拿不到任何一条留言内容。
  这不是脚本的缺陷，也不是换 UA / 加 Referer 能绕过的。

## 需要的四个值

| 参数 | 含义 | 来源 |
| --- | --- | --- |
| `uin` | 微信用户标识 | 微信内打开文章时请求头 / Cookie |
| `key` | 短期会话票据（数小时过期） | 同上 |
| `pass_ticket` | 会话票据（较长有效） | 同上 |
| `appmsg_token` | 与单篇文章绑定的令牌 | **文章页 HTML 里的 `var appmsg_token`**，脚本自动读取 |

其中 `appmsg_token` 脚本会自己从页面里取；前三个必须由用户提供。

## 获取方式

### 方式一：代理抓包（最通用）

1. 手机微信与电脑连同一网络，手机 WiFi 代理指向电脑上的 mitmproxy / Charles / Proxyman。
2. 安装并信任其根证书（iOS 需在「设置 → 通用 → 关于本机 → 证书信任设置」里手动开启）。
3. 手机微信里打开目标文章的留言区，翻一两页。
4. 在抓包工具里找 `mp.weixin.qq.com/mp/appmsg_comment` 请求，从其 Query 与 Cookie 中取
   `uin`、`key`、`pass_ticket`，写入 JSON：

```json
{
  "cookie": "uin=xxx; key=xxx; pass_ticket=xxx; wap_sid2=xxx",
  "uin": "MTIzNDU2Nzg5",
  "key": "0123456789abcdef0123456789abcdef01234567",
  "pass_ticket": "aBcD...=="
}
```

5. 保存为 `~/.wechat-creds.json`（建议 `chmod 600`），或放到本 skill 的 `scripts/../.creds.json`（会被自动读取）。

### 方式二：PC 微信 + 抓包代理

部分第三方工具（如基于代理拦截的公众号下载器）能在 PC 微信打开文章时顺带吐出这组凭证。
思路与方式一相同：从 `appmsg_comment` 或 `getappmsgext` 请求里取其鉴权参数。

### 方式三：浏览器 profile 复用

如果某个浏览器 profile 里登录过微信文章页且会话仍有效，可以用：

```bash
node scripts/wx_article.js fetch "<链接>" --browser --profile ~/path/to/profile
```

脚本在该页面上下文内直接 `fetch` 留言接口，从而继承 profile 的 Cookie。
这条路省配置，但依赖该 profile 的登录态是否活着，成功率不稳定。

## 有效期与失败表现

- `key` 通常几个小时失效；`pass_ticket` 稍长。过期后接口继续返回 `ret=-3`。
- 出现以下任一情况，就是凭证过期或无效：`ret=-3`、`errmsg: no session`、`cookie_count: 0`。
- 处理方式：重新抓一次，替换凭证文件；不要反复重试（会触发 `ret=200003` 限频）。

## 关于第三方付费接口

市面上有按次计费的「公众号留言 API」服务（无需自备微信账号与 Cookie）。
本 skill 不内置任何第三方密钥，也不代用户调用付费接口；如果用户明确要求走这条路，
由用户提供其 API 凭据并自行承担费用，再把返回结果贴回本地处理。

## 边界提醒

- 只能拿到「精选留言」——作者在后台筛过、选择展示的那些。未被选出的留言对外不存在任何入口。
- 留言下的回复以作者回复为主，楼中楼不一定完整。
- 留言内容属于发布者与留言者，归档自用可以，公开发布需谨慎。
