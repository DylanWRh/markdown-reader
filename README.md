# Local Markdown Reader

一个只读、本地优先的 Markdown 项目阅读器。界面采用三栏布局：左侧项目文件树、中间正文、右侧页内目录；项目内 Markdown 链接支持悬浮预览与无刷新跳转。

## 功能

- 以目录为入口，展示整个项目的文件结构
- 默认打开根目录的 `README.md`，其次是 `index.md`，否则打开排序最前的 Markdown
- 文件搜索、面包屑和页内目录
- 项目内相对链接与锚点链接的悬浮预览、点击跳转
- GitHub 风格 Markdown、原生 HTML 表格、任务列表和脚注
- Pygments 代码高亮与一键复制
- Mermaid 流程图和 MathJax 数学公式，前端资源已随包保存，可离线使用
- 本地图片、SVG 和其他项目资源；图片点击放大
- 阅读进度、阅读时间、移动端布局和打印样式
- 只监听 `127.0.0.1`，并阻止访问所选项目目录之外的文件

## 安装到 py310

在 `markdown-reader/` 目录执行：

```powershell
conda run -n py310 python -m pip install .
```

开发期间希望本地代码改动立即生效，也可以使用 editable 安装：

```powershell
conda run -n py310 python -m pip install -e .
```

## 使用

安装后可以在任意目录直接运行：

```powershell
conda run -n py310 readmd AgentSurvey
```

如果已经激活 `py310`：

```powershell
conda activate py310
readmd AgentSurvey
```

也可以指定目录内的初始文档或端口：

```powershell
readmd AgentGraphics-Survey --initial chapters/01-introduction.md --port 8765
```

如果不希望自动打开浏览器，追加 `--no-browser`。停止服务时在终端按 `Ctrl+C`。

## 快捷键

- `/`：聚焦左侧文件搜索框
- `Esc`：关闭链接预览、图片预览或移动端目录
- 文档变化后点击右上角刷新按钮重新读取
- `Ctrl/Cmd + 单击` 项目内链接可在新标签页打开

