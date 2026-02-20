# YouTube 直播流代理服务器 | 免梯播放 YouTube 直播源

**搭配 o11 等推流工具后制作免梯直播源，配合 TiviMate 在安卓盒子上打造完整 IPTV 直播频道列表

<img src="https://github.com/user-attachments/assets/4086416d-f73a-4108-9d82-084287447456" width="500" />

---



## 这是什么？


这个脚本部署在一台能访问 YouTube 的 VPS 上，自动提取 YouTube 直播的真实流地址，

把播放地址转换成例如 http://你的VPS地址:61179/@TVBSNEWS01。这个地址需要挂梯子。什么？你不想挂梯？

配合 o11 等推流工具转推后，**国内设备无需梯子，手机、电视、盒子均可直接收看**。

---

## 安装与运行

**安装依赖**
```bash
pip install flask yt-dlp requests psutil -q --break-system-packages
```

**运行**（需要 VPS 能访问 YouTube）
```bash
python3 /root/py-ytblive.py
```

**rc.local 开机自启**
```
nohup python3 /root/py-ytblive.py > /var/log/py-ytblive.log 2>&1 &
```

---

## 使用方法

直播源格式如下：
```
http://你的VPS地址:61179/@TVBSNEWS01
```

频道名（如 `@TVBSNEWS01`）来自 YouTube 直播频道的地址栏，**理论上支持任何 YouTube 直播频道**，直接复制直播频道点进去头像 地址栏 `@` 后面的部分填入即可。

搭配 o11 等推流工具后制作免梯直播源，配合 TiviMate 在安卓盒子上获得极佳体验

  
可供以下应用直接使用：
- 安卓：**IPTV**、**TiviMate** 等
- 苹果：**APTVPlayer** 等
- 推流工具：**o11** 等



---

## 主要特性

- **双层缓存设计**：频道→视频ID（5分钟）+ 视频ID→流URL（30分钟），已缓存频道响应 <1 秒
- **自动定时刷新**：每30分钟后台自动续期，流地址过期自动续命，无需人工干预
- **多频道统一管理**：在脚本顶部配置好频道列表，服务启动自动预热缓存
- **两种播放模式**：默认重定向模式兼容 PotPlayer；加 `?redirect=false` 切换代理模式供 OBS 等使用
- **管理接口齐全**：`/cache/status` 查看缓存、`/cache/refresh` 手动刷新、`/health` 健康检查

---

## 脚本内预配置频道

在脚本顶部 `AUTO_CACHE_CHANNELS` 列表中填入频道名，服务启动时自动预热，访问延迟极低：

```python
AUTO_CACHE_CHANNELS = [
    '@ABCNews',
    '@SkyNews',
    '@mirrornow',
    'TVBSNEWS01'
]
```

---

