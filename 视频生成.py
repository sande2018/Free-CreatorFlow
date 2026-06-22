import requests
import time
import subprocess
import os

# ========== 配置 ==========
API_KEY = "你在agnes-ai的API key（免费无限量）"

CREATE_URL = "https://apihub.agnes-ai.com/v1/videos"
QUERY_URL = "https://apihub.agnes-ai.com/agnesapi"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


# ========== 创建视频任务 ==========
def create_video(prompt, image_url=None):
    """创建视频生成任务。
    
    Args:
        prompt: 视频内容的文本描述
        image_url: 可选，图片URL用于图生视频模式（将静态图片动画化）
    """
    payload = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "width": 1152,
        "height": 768,
        "num_frames": 121,
        "frame_rate": 24
    }

    # 如果提供了图片URL，启用图生视频模式
    if image_url:
        payload["image"] = image_url

    response = requests.post(
        CREATE_URL,
        headers=HEADERS,
        json=payload
    )

    if response.status_code != 200:
        print("创建任务失败")
        print(response.status_code)
        print(response.text)
        return None

    data = response.json()

    print("任务创建成功")
    print(data)

    return data.get("video_id")


# ========== 提取视频最后一帧 ==========
def extract_last_frame(video_path, output_image_path):
    """使用 ffmpeg 提取视频的最后一帧，保存为图片。
    
    Args:
        video_path: 视频文件路径
        output_image_path: 输出图片路径（如 .jpg / .png）
    
    Returns:
        bool: 提取成功返回 True，否则返回 False
    """
    try:
        # 方式1：通过 -sseof 从视频末尾 seek，取最后一帧
        cmd = [
            'ffmpeg', '-y', '-sseof', '-1', '-i', video_path,
            '-update', '1', '-q:v', '1', output_image_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return os.path.exists(output_image_path)

    except subprocess.CalledProcessError:
        # 方式2 fallback：用 ffprobe 获取总帧数，再用 select 滤镜
        try:
            probe_cmd = [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=duration,r_frame_rate',
                '-of', 'json', video_path
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            import json
            info = json.loads(result.stdout)
            stream = info.get('streams', [{}])[0]
            duration = float(stream.get('duration', 0))
            fps_str = stream.get('r_frame_rate', '24/1')
            num, den = fps_str.split('/')
            fps = float(num) / float(den)
            last_frame = int(duration * fps) - 1

            if last_frame > 0:
                cmd = [
                    'ffmpeg', '-y', '-i', video_path,
                    '-vf', f'select=eq(n\\,{last_frame})',
                    '-vframes', '1', output_image_path
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                return os.path.exists(output_image_path)
        except Exception:
            pass
        return False
    except Exception:
        return False


# ========== 查询任务 ==========
def query_video(video_id):
    url = f"{QUERY_URL}?video_id={video_id}"

    response = requests.get(
        url,
        headers=HEADERS
    )

    if response.status_code != 200:
        print("查询失败")
        print(response.status_code)
        print(response.text)
        return None

    return response.json()


# ========== 下载视频 ==========
def download_video(video_url, save_path="output.mp4"):
    response = requests.get(video_url)

    with open(save_path, "wb") as f:
        f.write(response.content)

    print(f"视频已保存：{save_path}")


# ========== 主流程 ==========
def generate_video(prompt):
    # 1. 创建任务
    video_id = create_video(prompt)

    if not video_id:
        return

    print(f"video_id: {video_id}")

    # 2. 轮询查询
    while True:
        result = query_video(video_id)

        if not result:
            return

        status = result.get("status")
        progress = result.get("progress", 0)

        print(f"状态: {status} | 进度: {progress}%")

        # 任务完成
        if status == "completed":
            video_url = result.get("remixed_from_video_id")

            print("视频生成完成")
            print("视频地址：")
            print(video_url)

            # 下载视频
            download_video(video_url)

            break

        # 任务失败
        elif status == "failed":
            print("视频生成失败")
            print(result)
            break

        # 等待5秒继续查询
        time.sleep(5)


# ========== 运行 ==========
if __name__ == "__main__":
    prompt = """
    A cinematic shot of a cat walking on the beach at sunset,
    soft ocean waves,
    warm golden lighting,
    realistic motion
    """

    generate_video(prompt)