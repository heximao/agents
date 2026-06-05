# 邮件分类规则配置

## 默认分类

### 工作
工作相关邮件，包含关键词：
- 工作、会议、项目、报告、任务
- deadline、meeting、project、report

### 账单
财务相关邮件，包含关键词：
- 账单、支付、发票、扣款、还款、银行
- bill、payment、invoice、transaction

### 通知
系统通知类邮件，包含关键词：
- 通知、提醒、验证码、激活、确认
- notification、verify、alert、confirm

### 订阅
订阅类邮件，包含关键词：
- 订阅、newsletter、推送、邮件列表
- unsubscribe、mailing list

### 个人
来自白名单联系人的邮件。需要在配置文件中设置发件人白名单：

```json
{
  "whitelist": [
    "mom@family.com",
    "dad@family.com",
    "friend@example.com"
  ]
}
```

### 未分类
无法自动分类的邮件。

## 自定义分类

可在配置文件中添加自定义分类规则：

```json
{
  "categories": {
    "购物": ["淘宝", "京东", "订单", "快递", "配送"],
    "旅行": ["机票", "酒店", "行程", "航班", "booking"],
    "学习": ["课程", "作业", "学习", "考试", "作业"]
  }
}
```

自定义分类会与默认分类合并。
