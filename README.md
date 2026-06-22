

# 🎬 自媒体视频生成系统

基于 Agnes-Video-V2.0 和 Agnes-2.0-Flash API 的一站式自媒体视频生成平台，支持从脚本创作到视频合成的全流程自动化。

<img width="1920" height="896" alt="image" src="https://github.com/user-attachments/assets/7ebea180-0f0e-4cf5-8b6c-1f104e5f54b7" />

<img width="1583" height="749" alt="image" src="https://github.com/user-attachments/assets/5fdf0aab-ff4c-4e97-96af-b341ac751a71" />

<img width="1542" height="864" alt="image" src="https://github.com/user-attachments/assets/c122843f-6cdf-423e-a51b-8866ff846acb" />

<img width="1550" height="1080" alt="image" src="https://github.com/user-attachments/assets/87a098a2-6ed2-4e41-b9f6-56820206c721" />


## ✨ 功能特性

### 📝 智能脚本生成
- AI 自动生成短视频脚本（标题、开头钩子、正文场景、结尾引导）
- 支持自定义主题和提示词
- 输出抖音/小红书风格爆款标题建议

### 🖼️ 主图生成
- 基于脚本内容生成视频封面图
- 支持重新生成和自定义描述

### 🎥 多场景视频生成
- **文生视频**：根据文本描述直接生成视频
- **图生视频**：将静态图片动画化为动态视频
- **场景连贯性**：自动提取上一场景最后一帧作为下一场景起始帧
- 封面图作为第一个视频的起始帧

### 🔗 图床集成
- 自动上传提取的帧图片到外部图床
- 生成公网可访问的图片链接

### 📦 视频合并
- 使用 ffmpeg 将所有场景视频按顺序合并为完整视频
- 支持下载合并后的完整视频

### 📊 项目管理
- 保存和管理所有生成的项目
- 支持重新生成单个场景
- 轮询状态实时更新

## 🛠️ 技术栈

- **后端**：Flask 3.0+
- **前端**：原生 HTML/CSS/JavaScript
- **AI API**：Agnes-Video-V2.0、Agnes-2.0-Flash
- **视频处理**：FFmpeg
- **图床**：hanak.cn

## 📦 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/your-username/自媒体视频生成.git
cd 自媒体视频生成
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

⚠️ **重要**：项目中包含示例 API Key，请替换为你自己的密钥。

编辑以下文件中的 `API_KEY`：

- `文本生成.py` - Agnes-2.0-Flash API Key
- `视频生成.py` - Agnes-Video-V2.0 API Key

### 4. 启动服务

```bash
python app.py
```

访问 http://localhost:5000 即可使用。

## 🚀 使用流程

### 方式一：一键创作（推荐）

1. 输入视频主题
2. 点击「一键创作」
3. 系统自动生成脚本 → 主图 → 多个场景视频
4. 等待所有场景生成完成
5. 点击「合并视频」下载完整视频

### 方式二：分步创作

1. **生成脚本** → 编辑脚本内容
2. **生成主图** → 选择满意的封面图
3. **生成视频** → 每个场景独立生成
4. **合并视频** → 下载完整视频

## 📁 项目结构

```
自媒体视频生成/
├── app.py                 # Flask 主应用
├── 文本生成.py            # Agnes-2.0-Flash 文本生成
├── 文生图.py              # 图片生成模块
├── 视频生成.py            # Agnes-Video-V2.0 视频生成
├── 图床链接.py            # 图床上传模块
├── requirements.txt       # Python 依赖
├── ffmpeg.exe             # FFmpeg 可执行文件
├── templates/
│   └── index.html         # 前端页面
├── data/
│   └── projects/          # 项目数据存储
├── images/
│   └── frames/            # 提取的帧图片
└── static/
    └── videos/            # 生成的视频文件
```

## ⚙️ 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `BASE_URL` | 服务器公网地址（用于图床回调） | http://localhost:5000 |

## 📝 API 接口

### 创建视频任务

```
POST /api/video/generate
```

### 查询视频状态

```
GET /api/video/status/<task_id>
```

### 长视频状态查询

```
GET /api/long-video/status/<group_id>?brief=1
```

### 合并视频

```
POST /api/video/merge/<group_id>
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## ⚠️ 注意事项

1. **API Key 安全**：不要将包含真实 API Key 的代码提交到公开仓库
2. **网络环境**：需要能够访问 Agnes AI API Gateway
3. **FFmpeg**：项目已包含 Windows 版本的 ffmpeg.exe，其他系统请自行安装
4. **视频时长**：每个场景默认生成约 5 秒视频（121帧，24fps）

---

⭐ 如果这个项目对你有帮助，请给个 Star！
