# YouTube 直播流代理服务器

**一个让安卓机顶盒 / 苹果设备直接播放 YouTube 直播的 Python 脚本**

---

## 安装依赖

```bash
pip install flask yt-dlp requests psutil -q --break-system-packages
```

## 运行（需要 VPS 能访问 YouTube）

```bash
python3 /root/py-ytblive.py
```

## 后台运行

```bash
nohup python3 /root/py-ytblive.py > /var/log/py-ytblive.log 2>&1 &
```

---

## 使用说明

直播源格式如下：

```
http://你的VPS地址:51179/@TVBSNEWS01
```

频道名（如 `@TVBSNEWS01`）来自 YouTube 直播头像-点进去的地址栏，理论上支持任何 YouTube 直播频道。

可供以下 App 直接使用：
- 安卓：**IPTV**、**TiviMate** 等
- 苹果：**APTVPlayer** 等

配合 TiviMate 制作一套完整直播源，在安卓机顶盒上体验极佳 📺


---


**主要功能：**

- 输入频道名自动获取当前直播的真实流 URL，支持重定向和代理两种模式
- 双层缓存设计（频道→视频ID + 视频ID→流URL），已缓存频道响应 <1 秒
- 后台自动定时刷新，避免流 URL 过期失效
- 支持多频道统一管理，服务启动后自动预热缓存
- 提供 `/cache/status`、`/cache/refresh`、`/health` 等管理接口，方便运维

