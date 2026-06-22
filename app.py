# -*- coding: utf-8 -*-
import os
import sys
import json
import uuid
import subprocess
import time
import threading
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory

# 将当前目录加入模块搜索路径，以便导入同目录下的 API 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from 文本生成 import generate_text
from 文生图 import generate_image, save_image, IMAGE_DIR
from 视频生成 import create_video, query_video, download_video, extract_last_frame
from 图床链接 import upload_image

# ==================== Flask 配置 ====================
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, 'data', 'projects')
IMAGES_DIR = os.path.join(BASE_DIR, IMAGE_DIR)
VIDEOS_DIR = os.path.join(BASE_DIR, 'static', 'videos')
FRAMES_DIR = os.path.join(BASE_DIR, IMAGE_DIR, 'frames')

# 服务器公网访问地址，用于 Agnes API 回调获取提取的帧图片
# 本地开发时需配合 ngrok 等内网穿透工具使用
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

for d in [PROJECTS_DIR, IMAGES_DIR, VIDEOS_DIR, FRAMES_DIR]:
    os.makedirs(d, exist_ok=True)

# 存储异步视频任务状态
video_tasks = {}

# 存储长视频分组任务状态
long_video_groups = {}


# ==================== 辅助函数 ====================
def load_project(project_id):
    path = os.path.join(PROJECTS_DIR, f'{project_id}.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_project(project):
    path = os.path.join(PROJECTS_DIR, f'{project["id"]}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(project, f, ensure_ascii=False, indent=2)


def list_all_projects():
    projects = []
    for f in os.listdir(PROJECTS_DIR):
        if f.endswith('.json'):
            path = os.path.join(PROJECTS_DIR, f)
            with open(path, 'r', encoding='utf-8') as fp:
                projects.append(json.load(fp))
    projects.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return projects


# ==================== 页面路由 ====================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/images/<path:filename>')
def serve_image(filename):
    """提供图片和提取的帧图片"""
    return send_from_directory(IMAGES_DIR, filename)


@app.route('/static/videos/<path:filename>')
def serve_video(filename):
    return send_from_directory(VIDEOS_DIR, filename)


# ==================== 智能流水线 ====================
def _build_script_prompt(topic):
    return f"""你是一位资深的自媒体视频编导。请根据主题"{topic}"，创作一份完整的短视频脚本。

要求：
1. 标题：吸引眼球，带数字或悬念，不超过20字
2. 开头（前3秒）：用一句话抓住观众注意力（钩子）
3. 正文：分为3-5个场景，每个场景包含【画面描述】和【旁白/文案】
4. 结尾：引导关注、点赞、评论的话术
5. 推荐3个适合抖音/小红书的爆款标题

请用中文输出，格式清晰，使用 Markdown 标记。"""


def _build_image_prompt(topic, script_snippet):
    return (
        f"A stunning, high-quality cover image for a short video about: {topic}. "
        f"Key visual: {script_snippet}. "
        "Style: cinematic lighting, vibrant colors, modern and eye-catching, "
        "suitable as a social media thumbnail. No text or watermarks."
    )


def _build_video_prompt(topic, script_snippet):
    return (
        f"A cinematic short video about {topic}. "
        f"Scene: {script_snippet}. "
        "Smooth camera movement, professional lighting, high production value."
    )


def _extract_scene_list(script, topic):
    """Extract editable scene prompts from a generated script."""
    extract_prompt = (
        f'从以下分镜/视频脚本中，提取每个场景的画面描述。'
        f'严格按以下 JSON 数组格式输出，不要添加任何其他内容：\n\n'
        f'[{{"scene": 1, "description": "中文场景描述", "prompt": "English video prompt under 40 words"}}]\n\n'
        f'脚本内容：\n{script}'
    )
    scenes_json = generate_text(extract_prompt, max_tokens=2000, temperature=0.3)
    scenes = []
    try:
        json_start = scenes_json.find('[')
        json_end = scenes_json.rfind(']') + 1
        if json_start >= 0 and json_end > json_start:
            scenes = json.loads(scenes_json[json_start:json_end])
    except (json.JSONDecodeError, TypeError, AttributeError):
        scenes = []

    if not scenes:
        parts = re.split(r'(?:###\s*)?场景\s*[一二三四五六七八九十\d]+[：:。]', script)
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 20]
        scenes = [
            {
                'scene': i + 1,
                'description': part[:260],
                'prompt': f'A cinematic scene about {topic}: {part[:180]}, smooth camera movement, professional lighting'
            }
            for i, part in enumerate(parts[:8])
        ]

    if not scenes:
        scenes = [{
            'scene': 1,
            'description': topic,
            'prompt': f'A cinematic video about {topic}, smooth camera movement, professional lighting'
        }]

    scene_list = []
    for s in scenes[:8]:
        scene_list.append({
            'scene_num': s.get('scene', len(scene_list) + 1),
            'description': s.get('description') or s.get('prompt') or '',
            'prompt': s.get('prompt') or s.get('description') or '',
            'status': 'pending',
            'progress': 0,
            'task_id': None,
            'video_url': None,
            'local_path': None
        })
    return scene_list


def _project_scene_snapshot(scenes):
    return [
        {
            'scene_num': s['scene_num'],
            'description': s.get('description', ''),
            'prompt': s.get('prompt', ''),
            'status': s.get('status', 'pending'),
            'progress': s.get('progress', 0),
            'task_id': s.get('task_id'),
            'video_url': s.get('video_url'),
            'local_path': s.get('local_path'),
            'last_frame_path': s.get('last_frame_path'),
            'last_frame_url': s.get('last_frame_url'),
        }
        for s in scenes
    ]


@app.route('/api/pipeline', methods=['POST'])
def api_pipeline():
    """一键生成：主题 → 视频脚本 + 封面图"""
    data = request.json
    topic = (data.get('topic') or '').strip()
    if not topic:
        return jsonify({'error': '请输入创作主题'}), 400

    project_id = uuid.uuid4().hex[:8]
    project = {
        'id': project_id,
        'topic': topic,
        'script': None,
        'image_url': None,
        'image_local': None,
        'video_task_id': None,
        'video_url': None,
        'status': 'generating',
        'created_at': datetime.now().isoformat()
    }

    try:
        # 第1步：生成脚本
        script = generate_text(_build_script_prompt(topic))
        if not script:
            return jsonify({'error': '脚本生成失败，请稍后重试'}), 500
        project['script'] = script
        scenes = _extract_scene_list(script, topic)

        # 第2步：从脚本中提取关键画面，生成封面图
        # 让AI从脚本中提炼出最适合做封面的画面描述
        extract_prompt = (
            f'从以下视频脚本中，提取最适合做封面图的一个关键画面描述，'
            f'用英文输出，只输出画面描述，不超过30个词：\n\n{script}'
        )
        scene_desc = generate_text(extract_prompt, max_tokens=100, temperature=0.5)
        if not scene_desc:
            scene_desc = topic

        image_prompt = _build_image_prompt(topic, scene_desc.strip())
        image_url = generate_image(image_prompt)
        project['image_url'] = image_url

        # 下载图片到本地
        try:
            local_path = save_image(image_url)
            project['image_local'] = local_path
        except Exception:
            pass

        project['status'] = 'completed'
        project['long_video_group_id'] = project_id
        project['long_video_scenes'] = _project_scene_snapshot(scenes)
        project['total_scenes'] = len(scenes)
        project['completed_scenes'] = 0
        save_project(project)

        long_video_groups[project_id] = {
            'group_id': project_id,
            'project_id': project_id,
            'topic': topic,
            'script': script,
            'scenes': scenes,
            'total_scenes': len(scenes),
            'completed_scenes': 0,
            'status': 'draft',
            'created_at': project['created_at']
        }

        return jsonify({
            'success': True,
            'project': project
        })

    except Exception as e:
        project['status'] = 'failed'
        project['error'] = str(e)
        save_project(project)
        return jsonify({'error': f'生成失败: {str(e)}'}), 500


@app.route('/api/pipeline/full', methods=['POST'])
def api_pipeline_full():
    """完整流水线：主题 → 脚本 + 封面图 + 视频"""
    data = request.json
    topic = (data.get('topic') or '').strip()
    if not topic:
        return jsonify({'error': '请输入创作主题'}), 400

    project_id = uuid.uuid4().hex[:8]
    project = {
        'id': project_id,
        'topic': topic,
        'script': None,
        'image_url': None,
        'image_local': None,
        'video_task_id': None,
        'video_url': None,
        'status': 'generating',
        'created_at': datetime.now().isoformat()
    }

    try:
        # 第1步：生成脚本
        script = generate_text(_build_script_prompt(topic))
        if not script:
            return jsonify({'error': '脚本生成失败'}), 500
        project['script'] = script
        scenes = _extract_scene_list(script, topic)

        # 第2步：生成封面图
        extract_prompt = (
            f'从以下视频脚本中，提取最适合做封面图的一个关键画面描述，'
            f'用英文输出，只输出画面描述，不超过30个词：\n\n{script}'
        )
        scene_desc = generate_text(extract_prompt, max_tokens=100, temperature=0.5)
        if not scene_desc:
            scene_desc = topic

        image_url = generate_image(_build_image_prompt(topic, scene_desc.strip()))
        project['image_url'] = image_url
        try:
            project['image_local'] = save_image(image_url)
        except Exception:
            pass

        # 第3步：逐场景提交视频生成任务（异步）
        group = {
            'group_id': project_id,
            'project_id': project_id,
            'topic': topic,
            'script': script,
            'scenes': scenes,
            'total_scenes': len(scenes),
            'completed_scenes': 0,
            'status': 'processing',
            'created_at': project['created_at']
        }
        long_video_groups[project_id] = group
        project['long_video_group_id'] = project_id
        project['long_video_scenes'] = _project_scene_snapshot(scenes)
        project['total_scenes'] = len(scenes)
        project['completed_scenes'] = 0
        project['status'] = 'video_processing'
        save_project(project)

        t = threading.Thread(target=_long_video_worker, args=(project_id,), daemon=True)
        t.start()

        return jsonify({
            'success': True,
            'project': project
        })

    except Exception as e:
        project['status'] = 'failed'
        project['error'] = str(e)
        save_project(project)
        return jsonify({'error': f'生成失败: {str(e)}'}), 500


def _poll_video_task(video_task_id, project_id):
    """后台线程：轮询视频生成状态"""
    while True:
        try:
            result = query_video(video_task_id)
            if not result:
                video_tasks[video_task_id]['status'] = 'failed'
                break

            status = result.get('status', '')
            progress = result.get('progress', 0)
            video_tasks[video_task_id]['status'] = status
            video_tasks[video_task_id]['progress'] = progress

            if status == 'completed':
                video_url = result.get('remixed_from_video_id', '')
                video_tasks[video_task_id]['video_url'] = video_url

                # 下载视频
                if video_url:
                    video_filename = f'{project_id}.mp4'
                    video_path = os.path.join(VIDEOS_DIR, video_filename)
                    try:
                        download_video(video_url, video_path)
                        video_tasks[video_task_id]['local_path'] = f'static/videos/{video_filename}'
                    except Exception:
                        pass

                # 更新项目文件
                project = load_project(project_id)
                if project:
                    project['video_url'] = video_url
                    project['video_local'] = f'static/videos/{video_filename}'
                    project['status'] = 'completed'
                    save_project(project)
                break

            elif status == 'failed':
                project = load_project(project_id)
                if project:
                    project['status'] = 'video_failed'
                    save_project(project)
                break

            time.sleep(5)
        except Exception:
            time.sleep(10)


# ==================== 单独功能接口 ====================
@app.route('/api/script', methods=['POST'])
def api_script():
    """生成视频脚本"""
    data = request.json
    topic = (data.get('topic') or '').strip()
    custom_prompt = (data.get('prompt') or '').strip()

    prompt = custom_prompt if custom_prompt else _build_script_prompt(topic)
    if not topic and not custom_prompt:
        return jsonify({'error': '请输入主题或自定义提示词'}), 400

    result = generate_text(prompt)
    if result:
        return jsonify({'success': True, 'script': result})
    return jsonify({'error': '脚本生成失败'}), 500


@app.route('/api/image', methods=['POST'])
def api_image():
    """生成图片"""
    data = request.json
    prompt = (data.get('prompt') or '').strip()
    size = data.get('size', '1024x768')

    if not prompt:
        return jsonify({'error': '请输入图片描述'}), 400

    try:
        image_url = generate_image(prompt, size=size)
        local_path = None
        try:
            local_path = save_image(image_url)
        except Exception:
            pass
        return jsonify({
            'success': True,
            'image_url': image_url,
            'image_local': local_path
        })
    except Exception as e:
        return jsonify({'error': f'图片生成失败: {str(e)}'}), 500


@app.route('/api/video', methods=['POST'])
def api_video():
    """提交视频生成任务"""
    data = request.json
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': '请输入视频描述'}), 400

    task_id = create_video(prompt)
    if not task_id:
        return jsonify({'error': '视频任务创建失败'}), 500

    video_tasks[task_id] = {
        'project_id': None,
        'status': 'processing',
        'progress': 0,
        'video_url': None
    }

    t = threading.Thread(target=_poll_video_task_standalone, args=(task_id,), daemon=True)
    t.start()

    return jsonify({'success': True, 'task_id': task_id})


@app.route('/api/video/status/<task_id>')
def api_video_status(task_id):
    """查询视频生成状态"""
    task = video_tasks.get(task_id)
    if task:
        return jsonify(task)

    # 直接向API查询
    result = query_video(task_id)
    if result:
        return jsonify({
            'status': result.get('status', 'unknown'),
            'progress': result.get('progress', 0),
            'video_url': result.get('remixed_from_video_id', '')
        })
    return jsonify({'status': 'unknown', 'progress': 0}), 404


def _poll_video_task_standalone(task_id):
    """后台线程：独立视频任务轮询"""
    while True:
        try:
            result = query_video(task_id)
            if not result:
                video_tasks[task_id]['status'] = 'failed'
                break

            status = result.get('status', '')
            progress = result.get('progress', 0)
            video_tasks[task_id]['status'] = status
            video_tasks[task_id]['progress'] = progress

            if status == 'completed':
                video_url = result.get('remixed_from_video_id', '')
                video_tasks[task_id]['video_url'] = video_url
                if video_url:
                    video_filename = f'{task_id[:8]}.mp4'
                    video_path = os.path.join(VIDEOS_DIR, video_filename)
                    try:
                        download_video(video_url, video_path)
                        video_tasks[task_id]['local_path'] = f'static/videos/{video_filename}'
                    except Exception:
                        pass
                break
            elif status == 'failed':
                break

            time.sleep(5)
        except Exception:
            time.sleep(10)


# ==================== 长视频生成 ====================
def _build_long_script_prompt(topic):
    return f"""你是一位资深的短视频编导。请根据主题"{topic}"，创作一份分镜视频脚本。

严格要求：
1. 将内容分为 4-8 个场景（每个场景对应一个 5 秒的视频片段）
2. 每个场景必须用 "### 场景 N" 作为标题（N 为序号）
3. 每个场景下包含两部分：
   - 【画面描述】：详细描述这一场景的视觉画面（中文，用于理解内容）
   - 【英文画面】：用英文描述这个场景的动态画面，适合作为 AI 视频生成的提示词，包含镜头运动、光影、氛围等细节，不超过 40 个英文单词
4. 场景之间要有逻辑连贯性，形成完整的叙事
5. 第一个场景要有吸引力的开场，最后一个场景要有收尾

请用中文输出，格式清晰。"""


@app.route('/api/long-video', methods=['POST'])
def api_long_video():
    """长视频生成：根据主题自动拆分场景，逐场景生成视频片段"""
    data = request.json
    topic = (data.get('topic') or '').strip()
    if not topic:
        return jsonify({'error': '请输入创作主题'}), 400

    group_id = uuid.uuid4().hex[:8]

    # 第1步：生成分场景脚本
    script = generate_text(_build_long_script_prompt(topic))
    if not script:
        return jsonify({'error': '脚本生成失败，请稍后重试'}), 500

    # 第2步：初始化分组任务
    scene_list = _extract_scene_list(script, topic)

    group = {
        'group_id': group_id,
        'project_id': group_id,
        'topic': topic,
        'script': script,
        'scenes': scene_list,
        'total_scenes': len(scene_list),
        'completed_scenes': 0,
        'status': 'processing',
        'created_at': datetime.now().isoformat()
    }
    long_video_groups[group_id] = group

    # 第4步：启动后台工作线程，逐场景生成视频
    t = threading.Thread(target=_long_video_worker, args=(group_id,), daemon=True)
    t.start()

    return jsonify({
        'success': True,
        'group_id': group_id,
        'total_scenes': len(scene_list),
        'script': script
    })


def _long_video_worker(group_id):
    """后台线程：逐场景提交视频任务并轮询至完成，场景间传递最后一帧保证连贯性"""
    group = long_video_groups[group_id]
    scenes = group['scenes']
    # 第一个场景使用项目封面图作为起始帧，后续场景使用上一场景的最后一帧
    project = load_project(group.get('project_id') or group_id)
    last_frame_url = project.get('image_url') if project else None

    for i, scene in enumerate(scenes):
        scene['status'] = 'processing'
        prompt = scene['prompt']

        # 如果提示词不像英文，用 AI 翻译
        if prompt and not any(c.isascii() and c.isalpha() for c in prompt[:10]):
            translated = generate_text(
                f'Translate the following video scene description to English, '
                f'keeping it under 40 words, only output the translation:\n\n{prompt}',
                max_tokens=100, temperature=0.3
            )
            if translated:
                prompt = translated.strip()

        # 提交视频任务：如果有上一场景的最后一帧，则启用图生视频模式
        task_id = create_video(prompt, image_url=last_frame_url)
        if not task_id:
            scene['status'] = 'failed'
            continue

        scene['task_id'] = task_id

        # 同时注册到全局 video_tasks
        video_tasks[task_id] = {
            'project_id': None,
            'status': 'processing',
            'progress': 0,
            'video_url': None
        }

        # 轮询当前场景直到完成
        max_wait = 600  # 最多等 10 分钟
        waited = 0
        while waited < max_wait:
            try:
                result = query_video(task_id)
                if not result:
                    time.sleep(5)
                    waited += 5
                    continue

                status = result.get('status', '')
                progress = result.get('progress', 0)
                scene['status'] = status
                scene['progress'] = progress

                # 同步到全局
                if task_id in video_tasks:
                    video_tasks[task_id]['status'] = status
                    video_tasks[task_id]['progress'] = progress

                if status == 'completed':
                    video_url = result.get('remixed_from_video_id', '')
                    scene['video_url'] = video_url
                    if task_id in video_tasks:
                        video_tasks[task_id]['video_url'] = video_url

                    # 下载视频到本地
                    if video_url:
                        video_filename = f'{group_id}_scene{scene["scene_num"]:02d}.mp4'
                        video_path = os.path.join(VIDEOS_DIR, video_filename)
                        try:
                            download_video(video_url, video_path)
                            scene['local_path'] = f'static/videos/{video_filename}'
                            if task_id in video_tasks:
                                video_tasks[task_id]['local_path'] = scene['local_path']

                            # 提取最后一帧，供下一场景用作起始帧
                            frame_filename = f'{group_id}_scene{scene["scene_num"]:02d}_lastframe.jpg'
                            frame_path = os.path.join(FRAMES_DIR, frame_filename)
                            if extract_last_frame(video_path, frame_path):
                                scene['last_frame_path'] = f'images/frames/{frame_filename}'
                                # 上传到外部图床，获取公网可访问的URL
                                external_url = upload_image(frame_path)
                                if external_url:
                                    last_frame_url = external_url
                                    scene['last_frame_url'] = external_url
                                else:
                                    last_frame_url = None
                            else:
                                last_frame_url = None
                        except Exception:
                            last_frame_url = None
                            pass

                    group['completed_scenes'] += 1
                    project = load_project(group.get('project_id') or group_id)
                    if project:
                        project['long_video_scenes'] = _project_scene_snapshot(scenes)
                        project['completed_scenes'] = group['completed_scenes']
                        project['total_scenes'] = len(scenes)
                        save_project(project)
                    break

                elif status == 'failed':
                    scene['status'] = 'failed'
                    last_frame_url = None  # 失败的场景不传递帧
                    break

            except Exception:
                pass

            time.sleep(5)
            waited += 5

    # 所有场景处理完毕
    all_done = all(s['status'] in ('completed', 'failed') for s in scenes)
    any_completed = any(s['status'] == 'completed' for s in scenes)
    group['status'] = 'completed' if any_completed else 'failed'

    # 保存到项目
    project_id = group.get('project_id') or group_id
    project = load_project(project_id) or {
        'id': project_id,
        'topic': group['topic'],
        'script': group['script'],
        'created_at': group['created_at']
    }
    project.update({
        'long_video_group_id': group_id,
        'long_video_scenes': _project_scene_snapshot(scenes),
        'total_scenes': len(scenes),
        'completed_scenes': group['completed_scenes'],
        'status': 'long_video_completed' if any_completed else 'failed',
    })
    save_project(project)


@app.route('/api/long-video/status/<group_id>')
def api_long_video_status(group_id):
    """查询长视频生成状态（含所有场景详情）。
    
    支持 ?brief=1 参数，跳过 script 字段以减小轮询响应体积。
    """
    group = long_video_groups.get(group_id)
    if not group:
        return jsonify({'error': '任务不存在'}), 404

    total = group['total_scenes']
    completed = group['completed_scenes']
    # 计算总进度：已完成场景占比 + 当前进行中场景的进度
    scene_progress_sum = sum(s.get('progress', 0) for s in group['scenes'])
    overall_progress = int(scene_progress_sum / total) if total > 0 else 0

    brief = request.args.get('brief') == '1'

    result = {
        'group_id': group_id,
        'topic': group['topic'],
        'status': group['status'],
        'total_scenes': total,
        'completed_scenes': completed,
        'overall_progress': overall_progress,
        'scenes': [
            {
                'scene_num': s['scene_num'],
                'description': s.get('description', ''),
                'prompt': s['prompt'],
                'status': s['status'],
                'progress': s.get('progress', 0),
                'video_url': s.get('video_url'),
                'local_path': s.get('local_path'),
                'last_frame_path': s.get('last_frame_path'),
                'last_frame_url': s.get('last_frame_url'),
            }
            for s in group['scenes']
        ]
    }

    if not brief:
        result['script'] = group['script']

    return jsonify(result)


@app.route('/api/video/merge/<group_id>', methods=['POST'])
def api_video_merge(group_id):
    """使用 ffmpeg 将所有场景视频按顺序合并为一个视频"""
    # 尝试从内存中获取 group
    group = long_video_groups.get(group_id)
    if not group:
        # 尝试从项目文件加载
        project = load_project(group_id)
        if project and project.get('long_video_scenes'):
            group = {
                'group_id': group_id,
                'scenes': project.get('long_video_scenes', []),
                'topic': project.get('topic', ''),
            }
        else:
            return jsonify({'error': '任务不存在'}), 404

    scenes = group['scenes']
    # 收集所有已完成的场景视频本地路径
    video_paths = []
    for s in sorted(scenes, key=lambda x: int(x.get('scene_num', 0))):
        local_path = s.get('local_path')
        if local_path and s.get('status') == 'completed':
            full_path = os.path.join(BASE_DIR, local_path)
            if os.path.exists(full_path):
                video_paths.append(full_path)

    if len(video_paths) < 2:
        return jsonify({'error': '至少需要2个已完成的场景视频才能合并'}), 400

    # 创建 ffmpeg concat 文件列表
    topic_slug = group.get('topic', group_id)[:20].replace(' ', '_')
    merged_filename = f'{group_id}_merged_{topic_slug}.mp4'
    merged_path = os.path.join(VIDEOS_DIR, merged_filename)
    list_path = os.path.join(VIDEOS_DIR, f'{group_id}_concat_list.txt')

    try:
        # 写入文件列表
        with open(list_path, 'w', encoding='utf-8') as f:
            for vp in video_paths:
                f.write(f"file '{vp}'\n")

        # 使用 ffmpeg concat 合并
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_path, '-c', 'copy', merged_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # 清理临时文件
        try:
            os.remove(list_path)
        except Exception:
            pass

        if result.returncode != 0:
            print(f"ffmpeg 合并失败: {result.stderr}")
            return jsonify({'error': f'视频合并失败: {result.stderr[:200]}'}), 500

        merged_url = f'static/videos/{merged_filename}'
        return jsonify({
            'success': True,
            'merged_url': merged_url,
            'merged_filename': merged_filename,
            'scene_count': len(video_paths)
        })

    except Exception as e:
        try:
            os.remove(list_path)
        except Exception:
            pass
        return jsonify({'error': f'合并失败: {str(e)}'}), 500


@app.route('/api/pipeline/cover/regenerate', methods=['POST'])
def api_pipeline_cover_regenerate():
    """重新生成一键创作主图"""
    data = request.json
    project_id = (data.get('project_id') or '').strip()
    prompt = (data.get('prompt') or '').strip()
    project = load_project(project_id) if project_id else None

    if not prompt:
        if not project:
            return jsonify({'error': '请输入主图描述'}), 400
        prompt = _build_image_prompt(
            project.get('topic', ''),
            (project.get('script') or project.get('topic') or '')[:300]
        )

    try:
        image_url = generate_image(prompt)
        local_path = None
        try:
            local_path = save_image(image_url)
        except Exception:
            pass

        if project:
            project['image_url'] = image_url
            project['image_local'] = local_path
            project['cover_prompt'] = prompt
            save_project(project)

        return jsonify({
            'success': True,
            'image_url': image_url,
            'image_local': local_path
        })
    except Exception as e:
        return jsonify({'error': f'主图生成失败: {str(e)}'}), 500


@app.route('/api/long-video/scene/regenerate', methods=['POST'])
def api_long_video_scene_regenerate():
    """编辑描述后重新生成单个场景视频"""
    data = request.json
    group_id = (data.get('group_id') or '').strip()
    scene_num = int(data.get('scene_num') or 0)
    description = (data.get('description') or '').strip()
    prompt = (data.get('prompt') or description).strip()

    group = long_video_groups.get(group_id)
    if not group:
        project = load_project(group_id)
        if project and project.get('long_video_scenes'):
            group = {
                'group_id': group_id,
                'project_id': project.get('id', group_id),
                'topic': project.get('topic', ''),
                'script': project.get('script', ''),
                'scenes': project.get('long_video_scenes', []),
                'total_scenes': len(project.get('long_video_scenes', [])),
                'completed_scenes': project.get('completed_scenes', 0),
                'status': project.get('status', 'draft'),
                'created_at': project.get('created_at', datetime.now().isoformat())
            }
            long_video_groups[group_id] = group

    if not group:
        return jsonify({'error': '场景任务不存在'}), 404

    scene = next((s for s in group['scenes'] if int(s.get('scene_num', 0)) == scene_num), None)
    if not scene:
        return jsonify({'error': '场景不存在'}), 404

    scene['description'] = description or scene.get('description', '')
    scene['prompt'] = prompt
    scene['status'] = 'processing'
    scene['progress'] = 0
    scene['task_id'] = None
    scene['video_url'] = None
    scene['local_path'] = None
    group['status'] = 'processing'

    project = load_project(group.get('project_id') or group_id)
    if project:
        project['long_video_scenes'] = _project_scene_snapshot(group['scenes'])
        project['status'] = 'video_processing'
        save_project(project)

    t = threading.Thread(target=_regenerate_single_scene_worker, args=(group_id, scene_num), daemon=True)
    t.start()

    return jsonify({'success': True, 'group_id': group_id, 'scene_num': scene_num})


def _regenerate_single_scene_worker(group_id, scene_num):
    """后台线程：重新生成单个场景，并提取末帧供后续场景使用"""
    group = long_video_groups[group_id]
    scene = next((s for s in group['scenes'] if int(s.get('scene_num', 0)) == scene_num), None)
    if not scene:
        return

    # 查找前一个已完成场景的最后一帧 URL，用于图生视频保证连贯性
    prev_frame_url = None
    if scene_num > 1:
        prev_scene = next(
            (s for s in group['scenes'] 
             if int(s.get('scene_num', 0)) == scene_num - 1 and s.get('status') == 'completed'),
            None
        )
        if prev_scene:
            # 优先使用外部图床链接，否则回退到本地URL
            prev_frame_url = prev_scene.get('last_frame_url') or (
                f'{BASE_URL}/{prev_scene["last_frame_path"]}' if prev_scene.get('last_frame_path') else None
            )

    prompt = scene.get('prompt') or scene.get('description') or group.get('topic', '')
    if prompt and not any(c.isascii() and c.isalpha() for c in prompt[:10]):
        translated = generate_text(
            f'Translate the following video scene description to English, '
            f'keeping it under 40 words, only output the translation:\n\n{prompt}',
            max_tokens=100, temperature=0.3
        )
        if translated:
            prompt = translated.strip()
            scene['prompt'] = prompt

    task_id = create_video(prompt, image_url=prev_frame_url)
    if not task_id:
        scene['status'] = 'failed'
        return

    scene['task_id'] = task_id
    video_tasks[task_id] = {
        'project_id': group.get('project_id'),
        'status': 'processing',
        'progress': 0,
        'video_url': None
    }

    max_wait = 600
    waited = 0
    while waited < max_wait:
        try:
            result = query_video(task_id)
            if not result:
                time.sleep(5)
                waited += 5
                continue

            status = result.get('status', '')
            progress = result.get('progress', 0)
            scene['status'] = status
            scene['progress'] = progress
            video_tasks[task_id]['status'] = status
            video_tasks[task_id]['progress'] = progress

            if status == 'completed':
                video_url = result.get('remixed_from_video_id', '')
                scene['video_url'] = video_url
                video_tasks[task_id]['video_url'] = video_url
                if video_url:
                    video_filename = f'{group_id}_scene{scene_num:02d}_{task_id[:6]}.mp4'
                    video_path = os.path.join(VIDEOS_DIR, video_filename)
                    try:
                        download_video(video_url, video_path)
                        scene['local_path'] = f'static/videos/{video_filename}'
                        video_tasks[task_id]['local_path'] = scene['local_path']

                        # 提取最后一帧，供下一场景用作起始帧
                        frame_filename = f'{group_id}_scene{scene_num:02d}_{task_id[:6]}_lastframe.jpg'
                        frame_path = os.path.join(FRAMES_DIR, frame_filename)
                        if extract_last_frame(video_path, frame_path):
                            scene['last_frame_path'] = f'images/frames/{frame_filename}'
                            external_url = upload_image(frame_path)
                            if external_url:
                                scene['last_frame_url'] = external_url
                    except Exception:
                        pass
                break
            if status == 'failed':
                scene['status'] = 'failed'
                break
        except Exception:
            pass
        time.sleep(5)
        waited += 5

    completed = sum(1 for s in group['scenes'] if s.get('status') == 'completed')
    group['completed_scenes'] = completed
    if all(s.get('status') in ('completed', 'failed') for s in group['scenes']):
        group['status'] = 'completed' if completed else 'failed'
    else:
        group['status'] = 'draft'

    project = load_project(group.get('project_id') or group_id)
    if project:
        project['long_video_scenes'] = _project_scene_snapshot(group['scenes'])
        project['completed_scenes'] = completed
        project['total_scenes'] = len(group['scenes'])
        project['status'] = 'long_video_completed' if completed else project.get('status', 'completed')
        save_project(project)


# ==================== AI 辅助 ====================
@app.route('/api/ai/optimize', methods=['POST'])
def api_ai_optimize():
    """AI优化提示词/标题"""
    data = request.json
    content = (data.get('content') or '').strip()
    action = data.get('action', 'optimize')  # optimize / title / tags

    if not content:
        return jsonify({'error': '请输入内容'}), 400

    prompts = {
        'optimize': f'请优化以下文本，使其更吸引人、更适合自媒体传播，保持原意不变：\n\n{content}',
        'title': f'请根据以下内容，生成5个吸引眼球的自媒体标题（适合抖音/小红书风格），每个标题不超过20字：\n\n{content}',
        'tags': f'请根据以下内容，推荐10个适合的自媒体标签/话题标签，用于提升曝光量：\n\n{content}',
    }

    prompt = prompts.get(action, prompts['optimize'])
    result = generate_text(prompt, max_tokens=512, temperature=0.8)
    if result:
        return jsonify({'success': True, 'result': result})
    return jsonify({'error': 'AI优化失败'}), 500


# ==================== 项目管理 ====================
@app.route('/api/projects')
def api_projects():
    """获取所有项目"""
    projects = list_all_projects()
    return jsonify({'projects': projects})


@app.route('/api/project/<project_id>')
def api_project_detail(project_id):
    """获取项目详情"""
    project = load_project(project_id)
    if project:
        return jsonify({'project': project})
    return jsonify({'error': '项目不存在'}), 404


@app.route('/api/project/<project_id>', methods=['DELETE'])
def api_project_delete(project_id):
    """删除项目"""
    path = os.path.join(PROJECTS_DIR, f'{project_id}.json')
    if os.path.exists(path):
        os.remove(path)
        return jsonify({'success': True})
    return jsonify({'error': '项目不存在'}), 404


# ==================== 启动 ====================
if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("  自媒体创作平台已启动")
    print("  请访问: http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)
