#coding=utf-8
#!/usr/bin/python
import re
import sys
import json
import html
import time
from urllib.parse import quote, unquote
import requests
from base.spider import Spider

sys.path.append('..')

class Spider(Spider):
    def getName(self):
        return "YouTube视频"

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend)
        except:
            self.extendDict = {}
        
        self.session = requests.Session()
        
        # --- 增强型代理配置逻辑 ---
        self.proxy_str = None
        if 'proxy' in self.extendDict:
            proxy_val = self.extendDict['proxy']
            if proxy_val:
                if isinstance(proxy_val, str):
                    self.proxy_str = proxy_val
                    # 检查是否已经是协议开头，否则默认补全
                    if not (proxy_val.startswith('http') or proxy_val.startswith('socks5')):
                        # 如果包含 '@' 或者端口常见于 SOCKS，可以手动改这里，默认设为 socks5
                        p_url = f'socks5://{proxy_val}'
                    else:
                        p_url = proxy_val
                    
                    self.session.proxies = {'http': p_url, 'https': p_url}
                elif isinstance(proxy_val, dict):
                    self.session.proxies = proxy_val
        
        # 即使没有外部输入，如果你想在代码里写死代理，取消下面两行的注释：
        # debug_proxy = "socks5://127.0.0.1:1080"
        # self.session.proxies = {'http': debug_proxy, 'https': debug_proxy}
        # -----------------------

        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.youtube.com"
        }
        self.session.headers.update(self.header)
        
        self.config = {}
        if 'json' in self.extendDict:
            try:
                config_url = self.extendDict['json']
                if config_url.startswith('./'):
                    import os
                    config_path = os.path.join(os.path.dirname(__file__), config_url[2:])
                    with open(config_path, 'r', encoding='utf-8') as f:
                        self.config = json.load(f)
                else:
                    r = self.session.get(config_url, timeout=5)
                    self.config = r.json()
            except:
                pass
        
        self.continuation_cache = {}

    def homeContent(self, filter):
        result = {}
        result['class'] = self.config.get('class', [
            {'type_id': '全部', 'type_name': '全部'},
            {'type_id': '电视剧', 'type_name': '电视剧'},
            {'type_id': '电影', 'type_name': '电影'},
            {'type_id': '短剧', 'type_name': '短剧'},
            {'type_id': '动漫', 'type_name': '动漫'},
            {'type_id': '音乐', 'type_name': '音乐'},
            {'type_id': '游戏', 'type_name': '游戏'},
            {'type_id': '综艺', 'type_name': '综艺'},
            {'type_id': '新闻', 'type_name': '新闻'},
            {'type_id': '直播', 'type_name': '直播'}
        ])
        if filter and 'filters' in self.config:
            result['filters'] = self.config['filters']
        return result

    def homeVideoContent(self):
        result = {'list': []}
        try:
            url = "https://www.youtube.com/results?search_query=热门视频"
            r = self.session.get(url, timeout=5)
            result['list'] = self._extract_videos_fixed(r.text, 20)
        except:
            pass
        return result

    def _handle_pagination(self, page, search_keyword=None, channel_name=None, cache_prefix=None):
        videos = []
        has_more = False
        yt_key = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
        
        if page == 1:
            url = f"https://www.youtube.com/@{channel_name}/videos" if channel_name else f"https://www.youtube.com/results?search_query={quote(search_keyword)}"
            try:
                r = self.session.get(url, timeout=10)
                html_content = r.text
                videos = self._extract_videos_fixed(html_content, 30)
                token = self._extract_continuation_token(html_content)
                if token:
                    self.continuation_cache[f"{cache_prefix}_2"] = token
                    has_more = True
            except:
                pass
        else:
            token = self.continuation_cache.get(f"{cache_prefix}_{page}")
            if token:
                api_type = "browse" if channel_name else "search"
                api_url = f"https://www.youtube.com/youtubei/v1/{api_type}?key={yt_key}"
                payload = {
                    "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240310.01.00"}},
                    "continuation": token
                }
                try:
                    r = self.session.post(api_url, json=payload, timeout=10)
                    data = r.json()
                    videos = self._extract_videos_from_api(data, 30)
                    next_token = self._extract_next_continuation(data)
                    if next_token:
                        self.continuation_cache[f"{cache_prefix}_{page+1}"] = next_token
                        has_more = True
                except:
                    pass
        return videos, has_more

    def categoryContent(self, cid, page, filter, ext):
        page = int(page)
        videos = []
        has_more = False
        tid = ext.get('tid', cid)
        
        if tid.startswith('LIST:'):
            items = [x.strip() for x in tid[5:].split(',')]
            for item in items:
                if '@' in item and page == 1:
                    parts = item.split('@')
                    name = parts[0] if parts[0] else parts[1]
                    videos.append({"vod_id": f"channel_{parts[1]}", "vod_name": name, "vod_pic": "https://www.youtube.com/s/desktop/2ad2ef02/img/favicon_144x144.png", "vod_remarks": "频道"})
                elif '@' not in item:
                    v_list, m = self._handle_pagination(page, search_keyword=item, cache_prefix=f"search_{item}")
                    videos.extend(v_list)
                    if m: has_more = True
        elif tid.startswith('channel_'):
            videos, has_more = self._handle_pagination(page, channel_name=tid[8:], cache_prefix=tid)
        else:
            videos, has_more = self._handle_pagination(page, search_keyword=tid, cache_prefix=f"search_{tid}")

        res_list = []
        seen = set()
        for v in videos:
            if v['vod_id'] not in seen:
                res_list.append(v)
                seen.add(v['vod_id'])

        return {'list': res_list, 'page': page, 'pagecount': page + 1 if has_more else page, 'limit': len(res_list), 'total': len(res_list)}

    def detailContent(self, did):
        video_id = did[0]
        if video_id.startswith('channel_'):
            channel_name = video_id[8:]
            all_videos = []
            for p in range(1, 4):
                v, m = self._handle_pagination(p, channel_name=channel_name, cache_prefix=f"ch_{channel_name}")
                all_videos.extend(v)
                if not m: break
            
            play_urls = [f"{self._safe_title(v['vod_name'])}${v['vod_id']}" for v in all_videos]
            return {'list': [{"vod_id": video_id, "vod_name": f"频道: {channel_name}", "vod_pic": "https://www.youtube.com/s/desktop/2ad2ef02/img/favicon_144x144.png", "vod_play_from": "频道列表", "vod_play_url": "#".join(play_urls)}]}

        try:
            r = self.session.get(f"https://www.youtube.com/watch?v={video_id}", timeout=10)
            html_content = r.text
            
            author_match = re.search(r'"canonicalBaseUrl":"/([^"]+)"', html_content)
            author_id = author_match.group(1).replace('@', '') if author_match else ""
            
            title = self._get_video_title(video_id)
            related = self._extract_related_videos_fixed(html_content, video_id, 30)
            
            channel_v = []
            if author_id:
                channel_v, _ = self._handle_pagination(1, channel_name=author_id, cache_prefix="det_ch")

            play_url1 = f"{self._safe_title(title)}${video_id}"
            
            play_url2_parts = []
            for cv in channel_v:
                if cv['vod_id'] != video_id:
                    play_url2_parts.append(f"{self._safe_title(cv['vod_name'])}${cv['vod_id']}")
            
            play_url3_parts = []
            for rv in related:
                if rv['vod_id'] != video_id:
                    play_url3_parts.append(f"{self._safe_title(rv['vod_name'])}${rv['vod_id']}")

            vod = {
                "vod_id": video_id,
                "vod_name": title,
                "vod_pic": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                "vod_director": author_id,
                "vod_play_from": '当前视频$$$UP主频道$$$相关推荐',
                "vod_play_url": f"{play_url1}$$$" + "#".join(play_url2_parts) + "$$$" + "#".join(play_url3_parts)
            }
            return {'list': [vod]}
        except:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        v, m = self._handle_pagination(int(pg), search_keyword=key, cache_prefix=f"search_{key}")
        return {'list': v, 'page': pg, 'pagecount': int(pg) + 1 if m else pg}

    def playerContent(self, flag, pid, vipFlags):
        video_id = pid.split('$')[-1]
        res = {"parse": 1, "url": f"https://www.youtube.com/embed/{video_id}?autoplay=1", "header": json.dumps(self.header)}
        if self.proxy_str:
            res["proxy"] = self.proxy_str
        return res

    def _extract_videos_fixed(self, html_str, limit=30):
        try:
            data_match = re.search(r'var ytInitialData = (\{.*?\});', html_str)
            if data_match:
                return self._extract_videos_from_api(json.loads(data_match.group(1)), limit)
        except: pass
        return []

    def _extract_videos_from_api(self, data, limit=30):
        videos = []
        def scan(obj):
            if isinstance(obj, dict):
                if 'videoRenderer' in obj:
                    v = self._parse_renderer(obj['videoRenderer'])
                    if v: videos.append(v)
                elif 'compactVideoRenderer' in obj:
                    v = self._parse_renderer(obj['compactVideoRenderer'])
                    if v: videos.append(v)
                else:
                    for k in obj: scan(obj[k])
            elif isinstance(obj, list):
                for i in obj: scan(i)
        scan(data)
        return videos[:limit]

    def _parse_renderer(self, r):
        try:
            vid = r.get('videoId')
            if not vid: return None
            title_obj = r.get('title', {})
            title = title_obj.get('simpleText') or title_obj.get('runs', [{}])[0].get('text', 'YouTube Video')
            dur = r.get('lengthText', {}).get('simpleText', 'LIVE')
            return {"vod_id": vid, "vod_name": html.unescape(title), "vod_pic": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg", "vod_remarks": dur}
        except: return None

    def _extract_continuation_token(self, html_str):
        match = re.search(r'"continuationCommand":\{"token":"([^"]+)"', html_str)
        return match.group(1) if match else None

    def _extract_next_continuation(self, data):
        def find(obj):
            if isinstance(obj, dict):
                if 'continuationCommand' in obj: return obj['continuationCommand'].get('token')
                for k in obj:
                    res = find(obj[k]); 
                    if res: return res
            elif isinstance(obj, list):
                for i in obj:
                    res = find(i); 
                    if res: return res
            return None
        return find(data)

    def _extract_related_videos_fixed(self, html_str, current_id, limit=20):
        return self._extract_videos_fixed(html_str, limit)

    def _get_video_title(self, vid):
        try:
            r = self.session.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=3)
            return r.json().get('title', vid)
        except: return vid

    def _safe_title(self, title):
        if not title: return "video"
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def destroy(self):
        self.session.close()
