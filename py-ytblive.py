#!/usr/bin/env python3
"""
YouTube直播流代理服务器
支持PotPlayer等播放器通过HTTP接口播放YouTube直播
支持自动缓存刷新
#依赖pip install flask yt-dlp requests psutil -q --break-system-packages
poplayer使用范例：py运行后，poplayer ctrl+u 粘贴播放 http://www.vps域名/ip.com:51179/@TVBSNEWS01
"""

from flask import Flask, Response, request, jsonify, redirect as flask_redirect
import yt_dlp
import requests
import logging
import os
import sys
import signal
import threading
import time

# ============================================
# 配置区域 - 在这里修改你的设置
# ============================================

# 需要自动缓存的频道列表
AUTO_CACHE_CHANNELS = [
    '@ABCNews',
    '@SkyNews',
    '@mirrornow',
    'TVBSNEWS01'
]

# 自动刷新间隔 (秒) - 建议设置为15-30分钟,避免URL过期
AUTO_REFRESH_INTERVAL = 1800  # 每30分钟刷新一次

# 缓存过期时间 (秒) - YouTube流URL通常30-60分钟过期
CACHE_DURATION = 1800  # 缓存30分钟

# 频道缓存过期时间 (秒) - 频道->视频ID的映射
CHANNEL_CACHE_DURATION = 300  # 5分钟

# 视频分辨率 (像素)
VIDEO_MAX_HEIGHT = 1080  # 1080p (优先)

# 服务器设置
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 51179
LOG_FILE = '/var/log/youtube-proxy.log'
PID_FILE = '/var/run/youtube-proxy.pid'

# 是否启用自动刷新
ENABLE_AUTO_REFRESH = True

# ============================================
# 以下代码无需修改
# ============================================

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 双层缓存系统
url_cache = {}          # 视频ID -> 流URL的缓存
channel_cache = {}      # 频道名 -> 视频ID的缓存

def kill_existing_process():
    """停止已存在的youtube_proxy.py进程"""
    import psutil
    
    current_pid = os.getpid()
    killed = False
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['cmdline']:
                cmdline = ' '.join(proc.info['cmdline'])
                if 'youtube_proxy.py' in cmdline and proc.info['pid'] != current_pid:
                    logger.info(f"发现旧进程 PID: {proc.info['pid']}, 正在停止...")
                    proc.terminate()
                    proc.wait(timeout=5)
                    logger.info(f"? 已停止旧进程 PID: {proc.info['pid']}")
                    killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass
    
    if not killed:
        logger.info("未发现运行中的旧进程")
    
    return killed

def daemonize():
    """将进程转为后台守护进程"""
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.error(f"Fork失败: {e}")
        sys.exit(1)
    
    os.chdir('/')
    os.setsid()
    os.umask(0)
    
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.error(f"第二次Fork失败: {e}")
        sys.exit(1)
    
    sys.stdout.flush()
    sys.stderr.flush()
    
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    with open(LOG_FILE, 'a') as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())

def get_channel_live_video_id(channel_handle):
    """获取频道当前正在直播的视频ID (带缓存)"""
    
    # 规范化频道名
    channel_key = channel_handle
    if not channel_key.startswith('@') and not channel_key.startswith('http'):
        channel_key = f"@{channel_key}"
    
    # 检查频道缓存
    if channel_key in channel_cache:
        cache_entry = channel_cache[channel_key]
        cache_age = time.time() - cache_entry['timestamp']
        
        if cache_age < CHANNEL_CACHE_DURATION:
            video_id = cache_entry['video_id']
            logger.info(f"? 使用频道缓存: {channel_key} -> {video_id} (缓存: {int(cache_age)}秒)")
            return video_id
    
    # 构建频道URL
    if channel_handle.startswith('http'):
        channel_url = channel_handle
    elif channel_handle.startswith('@'):
        channel_url = f"https://www.youtube.com/{channel_handle}/live"
    else:
        channel_url = f"https://www.youtube.com/@{channel_handle}/live"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    
    try:
        logger.info(f"正在获取频道直播: {channel_handle}")
        start_time = time.time()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            video_id = info.get('id')
            
            if not video_id:
                raise Exception("频道当前没有直播")
            
            parse_time = time.time() - start_time
            logger.info(f"? 找到直播视频ID: {video_id} - 耗时: {parse_time:.2f}秒")
            
            # 存入频道缓存
            channel_cache[channel_key] = {
                'video_id': video_id,
                'timestamp': time.time()
            }
            
            return video_id
            
    except Exception as e:
        logger.error(f"? 获取频道直播失败: {str(e)}")
        raise

def get_youtube_stream_url(video_id):
    """获取YouTube直播流的真实URL (带缓存)"""
    # 检查缓存
    if video_id in url_cache:
        cache_entry = url_cache[video_id]
        cache_age = time.time() - cache_entry['timestamp']
        
        if cache_age < CACHE_DURATION:
            logger.info(f"? 使用缓存: {video_id} (缓存时间: {int(cache_age)}秒)")
            return cache_entry['url']
        else:
            logger.info(f"缓存已过期,重新获取: {video_id}")
    
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl_opts = {
        'format': f'bestvideo[height<={VIDEO_MAX_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/best[height<={VIDEO_MAX_HEIGHT}]/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    try:
        logger.info(f"开始解析YouTube视频: {video_id}")
        start_time = time.time()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            stream_url = info.get('url')
            
            height = info.get('height', 'unknown')
            width = info.get('width', 'unknown')
            parse_time = time.time() - start_time
            
            logger.info(f"? 成功获取视频流: {video_id} - {width}x{height} - 耗时: {parse_time:.2f}秒")
            
            # 存入缓存
            url_cache[video_id] = {
                'url': stream_url,
                'timestamp': time.time(),
                'resolution': f"{width}x{height}",
                'channel': None
            }
            
            return stream_url
            
    except Exception as e:
        logger.error(f"? 获取YouTube流失败: {str(e)}")
        raise

def refresh_channel_cache(channel):
    """刷新单个频道的缓存"""
    try:
        logger.info(f"[自动刷新] 开始刷新频道: {channel}")
        video_id = get_channel_live_video_id(channel)
        get_youtube_stream_url(video_id)
        
        # 记录频道名称
        if video_id in url_cache:
            url_cache[video_id]['channel'] = channel
        
        logger.info(f"[自动刷新] ? 完成: {channel} -> {video_id}")
        return True
    except Exception as e:
        logger.error(f"[自动刷新] ? 失败: {channel} - {str(e)}")
        return False

def refresh_all_channels():
    """刷新所有配置的频道"""
    if not AUTO_CACHE_CHANNELS:
        logger.info("[自动刷新] 没有配置频道")
        return
    
    logger.info(f"[自动刷新] 开始刷新 {len(AUTO_CACHE_CHANNELS)} 个频道...")
    success_count = 0
    
    for channel in AUTO_CACHE_CHANNELS:
        if refresh_channel_cache(channel):
            success_count += 1
        time.sleep(2)  # 避免请求过快
    
    logger.info(f"[自动刷新] 完成! 成功: {success_count}/{len(AUTO_CACHE_CHANNELS)}")

def auto_refresh_loop():
    """后台自动刷新循环"""
    if not ENABLE_AUTO_REFRESH:
        logger.info("[自动刷新] 功能已禁用")
        return
    
    logger.info(f"[自动刷新] 已启动,间隔: {AUTO_REFRESH_INTERVAL}秒 ({AUTO_REFRESH_INTERVAL/3600:.1f}小时)")
    
    # 启动时先刷新一次
    time.sleep(10)  # 等待服务器完全启动
    refresh_all_channels()
    
    # 定时刷新
    while True:
        time.sleep(AUTO_REFRESH_INTERVAL)
        refresh_all_channels()

def stream_generator(url):
    """流式传输生成器"""
    try:
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
    except Exception as e:
        logger.error(f"流传输错误: {str(e)}")
        raise

@app.route('/url/<path:channel_path>', methods=['GET'])
def get_stream_url(channel_path):
    """获取流URL端点 - 直接返回YouTube真实URL"""
    try:
        video_id = get_channel_live_video_id(channel_path)
        logger.info(f"频道 {channel_path} 当前直播ID: {video_id}")
        
        stream_url = get_youtube_stream_url(video_id)
        logger.info(f"返回流URL: {stream_url[:100]}...")
        
        # 直接重定向到YouTube流
        return flask_redirect(stream_url, code=302)
        
    except Exception as e:
        logger.error(f"获取URL失败: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/video', methods=['GET'])
def video_proxy():
    """视频代理端点"""
    video_id = request.args.get('id')
    channel = request.args.get('channel')
    redirect_mode = request.args.get('redirect', 'true').lower() == 'true'  # 默认重定向
    
    if channel:
        try:
            video_id = get_channel_live_video_id(channel)
            logger.info(f"频道 {channel} 当前直播ID: {video_id}")
        except Exception as e:
            return jsonify({'error': f'无法获取频道直播: {str(e)}'}), 500
    
    if not video_id:
        return jsonify({'error': '缺少视频ID或频道参数'}), 400
    
    try:
        stream_url = get_youtube_stream_url(video_id)
        
        # 如果请求重定向,直接返回302重定向到YouTube流URL
        if redirect_mode:
            logger.info(f"重定向模式: {video_id} -> {stream_url[:100]}...")
            return flask_redirect(stream_url, code=302)
        
        # 否则代理转发
        logger.info(f"代理模式: {video_id}")
        return Response(
            stream_generator(stream_url),
            mimetype='video/mp4',
            headers={
                'Accept-Ranges': 'bytes',
                'Content-Type': 'video/mp4'
            }
        )
    except Exception as e:
        logger.error(f"处理请求失败: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/<path:channel_path>', methods=['GET'])
def channel_proxy(channel_path):
    """频道路径代理端点"""
    try:
        video_id = get_channel_live_video_id(channel_path)
        logger.info(f"频道 {channel_path} 当前直播ID: {video_id}")
        
        stream_url = get_youtube_stream_url(video_id)
        
        return Response(
            stream_generator(stream_url),
            mimetype='video/mp4',
            headers={
                'Accept-Ranges': 'bytes',
                'Content-Type': 'video/mp4'
            }
        )
    except Exception as e:
        logger.error(f"处理请求失败: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'cached_videos': len(url_cache),
        'configured_channels': len(AUTO_CACHE_CHANNELS),
        'auto_refresh_enabled': ENABLE_AUTO_REFRESH,
        'refresh_interval_hours': AUTO_REFRESH_INTERVAL / 3600
    }), 200

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """清除缓存"""
    url_cache.clear()
    channel_cache.clear()
    logger.info("所有缓存已清除")
    return jsonify({'message': '所有缓存已清除'}), 200

@app.route('/cache/status', methods=['GET'])
def cache_status():
    """查看缓存状态"""
    # 视频流缓存
    video_cache_info = []
    for video_id, entry in url_cache.items():
        cache_age = int(time.time() - entry['timestamp'])
        video_cache_info.append({
            'video_id': video_id,
            'channel': entry.get('channel', 'unknown'),
            'resolution': entry.get('resolution', 'unknown'),
            'cache_age_seconds': cache_age,
            'expires_in_seconds': CACHE_DURATION - cache_age
        })
    
    # 频道缓存
    channel_cache_info = []
    for channel, entry in channel_cache.items():
        cache_age = int(time.time() - entry['timestamp'])
        channel_cache_info.append({
            'channel': channel,
            'video_id': entry['video_id'],
            'cache_age_seconds': cache_age,
            'expires_in_seconds': CHANNEL_CACHE_DURATION - cache_age
        })
    
    return jsonify({
        'video_cache': {
            'total': len(url_cache),
            'duration_minutes': CACHE_DURATION / 60,
            'items': video_cache_info
        },
        'channel_cache': {
            'total': len(channel_cache),
            'duration_minutes': CHANNEL_CACHE_DURATION / 60,
            'items': channel_cache_info
        },
        'auto_refresh_enabled': ENABLE_AUTO_REFRESH,
        'refresh_interval_minutes': AUTO_REFRESH_INTERVAL / 60,
        'configured_channels': AUTO_CACHE_CHANNELS
    }), 200

@app.route('/cache/refresh', methods=['POST'])
def manual_refresh():
    """手动触发刷新"""
    threading.Thread(target=refresh_all_channels, daemon=True).start()
    return jsonify({'message': '刷新任务已启动'}), 200

@app.route('/config', methods=['GET'])
def get_config():
    """获取当前配置"""
    return jsonify({
        'channels': AUTO_CACHE_CHANNELS,
        'auto_refresh_enabled': ENABLE_AUTO_REFRESH,
        'refresh_interval_seconds': AUTO_REFRESH_INTERVAL,
        'refresh_interval_minutes': AUTO_REFRESH_INTERVAL / 60,
        'cache_duration_seconds': CACHE_DURATION,
        'cache_duration_minutes': CACHE_DURATION / 60,
        'channel_cache_duration_seconds': CHANNEL_CACHE_DURATION,
        'channel_cache_duration_minutes': CHANNEL_CACHE_DURATION / 60,
        'video_max_height': VIDEO_MAX_HEIGHT,
        'server_host': SERVER_HOST,
        'server_port': SERVER_PORT
    }), 200

@app.route('/', methods=['GET'])
def index():
    """主页说明"""
    channels_html = '<br>'.join([
        f'<li><a href="/{ch}" target="_blank">{ch}</a> - <code>http://localhost:{SERVER_PORT}/{ch}</code></li>' 
        for ch in AUTO_CACHE_CHANNELS
    ])
    
    return f"""
    <h1>YouTube直播流代理服务器</h1>
    
    <h2>? 使用方法:</h2>
    
    <h3>方法1: 直接用频道名访问 ?推荐</h3>
    <ul>
        <li><strong>格式:</strong> http://your-server:{SERVER_PORT}/频道名</li>
        <li><strong>示例:</strong> <code>http://localhost:{SERVER_PORT}/@ABCNews</code></li>
        <li><strong>说明:</strong> 默认使用重定向模式,兼容PotPlayer</li>
    </ul>
    
    <h3>方法2: 通过参数访问</h3>
    <ul>
        <li><strong>频道(重定向):</strong> <code>http://localhost:{SERVER_PORT}/video?channel=@ABCNews</code></li>
        <li><strong>频道(代理):</strong> <code>http://localhost:{SERVER_PORT}/video?channel=@ABCNews&redirect=false</code></li>
        <li><strong>视频ID:</strong> <code>http://localhost:{SERVER_PORT}/video?id=VIDEO_ID</code></li>
    </ul>
    
    <h3>播放模式说明:</h3>
    <ul>
        <li><strong>重定向模式(默认):</strong> 服务器返回302重定向到YouTube真实流URL,适合PotPlayer</li>
        <li><strong>代理模式:</strong> 服务器代理转发视频流,适合OBS等工具</li>
        <li><strong>切换方式:</strong> 添加参数 <code>?redirect=false</code> 切换到代理模式</li>
    </ul>
    
    <h2>?? 已配置的频道 ({len(AUTO_CACHE_CHANNELS)}个 - 自动缓存):</h2>
    <ul>
        {channels_html}
    </ul>
    
    <h2>?? 管理接口:</h2>
    <ul>
        <li><a href="/cache/status">缓存状态</a> - <code>GET /cache/status</code></li>
        <li>清除缓存 - <code>POST /cache/clear</code></li>
        <li>手动刷新 - <code>POST /cache/refresh</code></li>
        <li><a href="/config">查看配置</a> - <code>GET /config</code></li>
        <li><a href="/health">健康检查</a> - <code>GET /health</code></li>
    </ul>
    
    <h2>?? 当前配置:</h2>
    <ul>
        <li>流缓存时长: {CACHE_DURATION}秒 ({CACHE_DURATION/60:.0f}分钟)</li>
        <li>频道缓存时长: {CHANNEL_CACHE_DURATION}秒 ({CHANNEL_CACHE_DURATION/60:.0f}分钟)</li>
        <li>自动刷新: {'? 启用' if ENABLE_AUTO_REFRESH else '? 禁用'}</li>
        <li>刷新间隔: {AUTO_REFRESH_INTERVAL}秒 ({AUTO_REFRESH_INTERVAL/60:.0f}分钟)</li>
        <li>视频分辨率: {VIDEO_MAX_HEIGHT}p</li>
        <li>流缓存数: {len(url_cache)} 个</li>
        <li>频道缓存数: {len(channel_cache)} 个</li>
    </ul>
    
    <h2>? 性能说明:</h2>
    <ul>
        <li><strong>已缓存频道:</strong> 访问速度 &lt;1秒 ???</li>
        <li><strong>未缓存频道:</strong> 首次访问 10-15秒</li>
        <li><strong>缓存刷新:</strong> 每{AUTO_REFRESH_INTERVAL/60:.0f}分钟自动更新</li>
        <li><strong>优化说明:</strong> 双层缓存 - 频道→视频ID({CHANNEL_CACHE_DURATION/60:.0f}分钟) + 视频ID→流URL({CACHE_DURATION/60:.0f}分钟)</li>
    </ul>
    
    <p style="color: #666; font-size: 12px;">
        日志文件: {LOG_FILE}<br>
        PID文件: {PID_FILE}<br>
        服务地址: http://{SERVER_HOST}:{SERVER_PORT}
    </p>
    """, 200

if __name__ == '__main__':
    logger.info("="*60)
    logger.info("YouTube直播流代理服务器启动中...")
    logger.info("="*60)
    
    # 停止旧进程
    try:
        kill_existing_process()
    except Exception as e:
        logger.warning(f"停止旧进程时出错: {e}")
    
    # 转为后台守护进程
    logger.info("转为后台守护进程...")
    daemonize()
    
    # 写入PID文件
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    # 启动自动刷新线程
    if ENABLE_AUTO_REFRESH and AUTO_CACHE_CHANNELS:
        threading.Thread(target=auto_refresh_loop, daemon=True).start()
    
    # 运行服务器
    logger.info(f"? 服务器启动在 http://{SERVER_HOST}:{SERVER_PORT} (PID: {os.getpid()})")
    logger.info(f"? 已配置 {len(AUTO_CACHE_CHANNELS)} 个频道: {', '.join(AUTO_CACHE_CHANNELS)}")
    logger.info(f"? 自动刷新: {'启用' if ENABLE_AUTO_REFRESH else '禁用'} (间隔: {AUTO_REFRESH_INTERVAL/60:.0f}分钟)")
    logger.info(f"? 双层缓存: 频道({CHANNEL_CACHE_DURATION/60:.0f}分钟) + 流URL({CACHE_DURATION/60:.0f}分钟)")
    logger.info(f"? 日志文件: {LOG_FILE}")
    logger.info("="*60)
    
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)