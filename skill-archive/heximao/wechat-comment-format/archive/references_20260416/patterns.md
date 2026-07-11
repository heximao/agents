# 精选留言排版详细规则

## 元数据处理

**必须保留** YAML frontmatter 区块（`---` 包围的部分），内容不变。

## 顶部原文链接

YAML 区块下方紧跟原文链接，格式：

```markdown
原文：[文章标题](文件名.md)

---
```

## 内容清理规则

### 可以删除的内容
- 超链接（URL 链接）
- 表情包/emoji（如 😂、👍、🙏 等）
- 微信特定标记（如"赞"、"顶"等）
- 用户名中的特殊字符
- 其他非文字的装饰性内容

### 严禁删除的内容
- 用户留言的文字内容
- 作者回复的文字内容
- 地区信息
- 用户名的中文或英文

## 留言格式规范

### 普通用户格式

`用户名`不加粗，不使用`##`标题格式，`留言内容`不使用引用格式

```markdown
用户名（地区）
留言内容
```

### 作者回复格式

```markdown
作者
回复内容
```

### 回复处理

用户回复其他用户时：

```markdown
用户名（地区）
回复 被回复用户名：回复内容
```

作者回复用户时：

```markdown
作者
回复 被回复用户名：回复内容
```

> 注意：当被回复用户名不明确或已被清理时，使用 `匿名` 代替。

## 分隔规则

每组对话（一条留言及其回复）之间使用 `---` 分隔：

```markdown
---

用户A（地区）
用户A的留言内容

天机奇谈
作者的回复内容

---

用户B（地区）
用户B的留言内容

---
```

## 空行规范

- 用户名与留言内容之间：**空行**
- 留言与回复之间：**一个空行**
- 回复与分隔线之间：**一个空行**
- 分隔线下一个用户之间：**一个空行**

## 特殊情况处理

### 地区缺失
当用户信息中没有地区时，直接使用用户名：

```markdown
用户名
留言内容
```

### 用户名包含特殊字符
删除特殊字符，仅保留中文和英文：

```markdown
用户名（北京）
留言内容
```

### 作者显示不统一
统一处理为"作者"格式。

## 完整示例

**排版前：**
```
 
- ![](https://wx.qlogo.cn/mmopen/PiajxSqBRaEJIcSQSM2eia8iabp8VJRrFRPxPxicZLUU0lU6YepM7jic8S6XeEicyNNPTMTdT7icdR8DAicK7gxgLH6vEE8WibceSsQuwe5mmFhDVibAATBRth0icibwCZrw0yEEgBnS/64)
    
    劉宇奇
    
    北京1小时前
    
    赞134
    
    随着市场的下跌，机哥的表达欲都上来了，到处都是打折的优质资产，确实让人兴奋![[偷笑]](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=)
    
    ![](https://wx.qlogo.cn/mmhead/Q3auHgzwzM7hibmTu7URBy7IicYFxT8roOqiayFCglFxOTibFribV7FqSUw/64)
    
    天机奇谈
    
    作者1小时前
    
    赞393
    
    这还没怎么兴奋，刚开始跌没多少，就跟只脱了外套似的，等脱到最里面的时候，就兴奋了![[捂脸]](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=)
```

**排版后：**
```
劉宇奇
随着市场的下跌，机哥的表达欲都上来了，到处都是打折的优质资产，确实让人兴奋

作者
这还没怎么兴奋，刚开始跌没多少，就跟只脱了外套似的，等脱到最里面的时候，就兴奋了
```
