# YouTube 直播流代理服务器

**一个让 PotPlayer 等播放器直接播放 YouTube 直播的 Python 工具**

**需要安装依赖

```pip install flask yt-dlp requests psutil -q --break-system-packages```


**使用范例
python3 /root/py-ytblive.py

**后台运行nohup python3 /root/py-ytblive.py > /var/log/youtube-proxy.log 2>&1 &

**之后potplayer url播放http://www.你的vps.com:51179/@TVBSNEWS01 即可实现播放TVBS新闻频道

---

## 介绍

YouTube 直播无法直接在 PotPlayer、VLC、OBS 等播放器中打开，每次都要手动用 yt-dlp 提取真实流地址，麻烦且容易过期。这个脚本搭建了一个本地 HTTP 代理服务，自动完成提取和缓存工作，让你直接把本地地址丢给播放器就能用。

**主要功能：**

- 输入频道名自动获取当前直播的真实流 URL，支持重定向和代理两种模式
- 双层缓存设计（频道→视频ID + 视频ID→流URL），已缓存频道响应 <1 秒
- 后台自动定时刷新，避免流 URL 过期失效
- 支持多频道统一管理，服务启动后自动预热缓存
- 提供 `/cache/status`、`/cache/refresh`、`/health` 等管理接口，方便运维

**适用场景：** 长期挂机收看 ABC News、Sky News 等 YouTube 直播频道，或搭配 IPTV 播放列表使用。
