# Font Glyph Extractor

## How to Run

### 一键测试（推荐）

```bash
docker-compose up --build
```

自动生成测试字体 → 提取字符 → 替换 → 验证输出，全程无需准备任何字体文件。输出文件在 `output/demo_result.ttf`。

### 使用自己的字体

```bash
# 1. 将字体文件放入 fonts/ 目录
# 2. 执行提取替换
docker-compose run --rm font-extractor extract \
  -s /data/fonts/source.ttf \
  -t /data/fonts/target.ttf \
  -o /data/output/result.ttf
```

### 本地方式（不用 Docker）

```bash
cd backend
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 一键演示
python -m src.main demo -d ./fonts -o ./output

# 使用自己的字体
python -m src.main extract -s source.ttf -t target.ttf -o output.ttf
```

### 其他命令

```bash
# 查看字体信息
docker-compose run --rm font-extractor info /data/fonts/test_source.ttf

# 检查字符是否存在
docker-compose run --rm font-extractor check /data/fonts/test_source.ttf

# 提取指定字符
docker-compose run --rm font-extractor extract \
  -s /data/fonts/test_source.ttf \
  -t /data/fonts/test_target.ttf \
  -o /data/output/result.ttf \
  -g "A,B,C,a,b,c"

# 显示默认字符列表
docker-compose run --rm font-extractor list-glyphs
```


### 如何测试

```bash
# 一行命令完成全流程测试（自动生成字体 → 提取 → 替换 → 验证）
docker-compose up --build

# 测试完成后，检查输出
# - output/demo_result.ttf 为生成的字体文件
# - fonts/test_source.ttf 为自动生成的源字体
# - fonts/test_target.ttf 为自动生成的目标字体

# 可用 FontForge 等工具打开 output/demo_result.ttf 验证字符是否正确替换
```


## Services

| 服务 | 说明 | 类型 |
|------|------|------|
| font-extractor | 字体字符提取替换工具 | CLI |

## 测试账号

无需账号，CLI 工具直接使用。

## 题目内容

新建一个python，我要支持一键提取一个字体的 
exclamdown 
cent 
sterling 
exclam 
quotedbl 
numbersign 
dollar 
percent 
ampersand 
quotesingle 
parenleft 
parenright 
asterisk 
plus 
comma 
hyphenminus 
period 
slash 
glyph22 
glyph23 
glyph24 
glyph25 
glyph26 
glyph27 
glyph28 
glyph29 
glyph30 
glyph31 
colon 
semicolon 
less 
equal 
greater 
question 
at 
A 
B 
C 
D 
E 
F 
G 
H 
I 
J 
K 
L 
M 
N 
O 
P 
Q 
R 
S 
T 
U 
V 
W 
X 
Y 
Z 
bracketleft 
backslash 
bracketright 
asciicircum 
underscore 
grave 
a 
b 
c 
d 
e 
f 
g 
h 
i 
j 
k 
l 
m 
n 
o 
p 
q 
r 
s 
t 
u 
v 
w 
x 
y 
z 
braceleft 
bar 
braceright 
asciitilde 
这些字符替换到另外一个字体里面，然后生成新的文件，要支持修改可变字体

## 项目介绍

Font Glyph Extractor 是一个 Python 命令行工具，从源字体文件中提取指定字符（glyph）的轮廓、度量等数据，替换到目标字体文件中，生成新的字体文件。

核心功能：
- 一键提取 90+ 预设字符并替换到目标字体
- 支持 TTF、OTF 等常见字体格式
- 支持可变字体（Variable Font）的变体数据提取和替换
- 自定义字符列表提取
- 字体信息查看和字符检查

技术栈：Python 3.11 / fonttools / click / loguru

### 目录结构

```
.
├── backend/                # 后端项目
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py           # CLI 入口
│   │   ├── font_extractor.py # 核心提取替换逻辑
│   │   ├── validator.py      # 验证模块
│   │   ├── config.py         # 配置管理
│   │   ├── exceptions.py     # 自定义异常
│   │   └── logger.py         # 日志配置
│   ├── Dockerfile
│   └── requirements.txt
├── docs/
│   └── project_design.md     # 设计文档
├── fonts/                    # 放置字体文件
├── output/                   # 输出目录
├── docker-compose.yml
├── .gitignore
└── README.md
```
