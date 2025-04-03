
# UI设计草图转代码全流程自动化流水线

## 名称
UI2Code全流程自动化流水线

## 描述
一个端到端的自动化流水线，将UI设计草图自动转化为完整可运行的前后端项目代码。
流水线集成了多个专业工具，依次完成UI分析、原型生成、API文档规划和前后端代码生成，大幅提升从设计到开发的效率。

## 主要功能
- 自动分析UI设计图，生成详细的线框原型描述
- 将线框描述转换为可交互的HTML原型界面
- 三步式生成完整API接口文档（功能分析、接口规划、文档生成）
- 生成基于Vue的完整前端项目，支持Vue2/Vue3和TypeScript
- 生成基于SpringBoot+MyBatis的完整后端项目，含数据库结构

## 技术优势
- 完整链路贯通：从单张UI图像到完整前后端项目的全流程自动化
- 高度可配置：支持自定义项目名称、包路径、前端框架版本等参数
- 多阶段优化：每个工具均实现多次重试机制，确保生成结果的质量
- 详细日志记录：完整跟踪每个阶段的执行情况和结果


## pipeline包含了以下几个工具：
- wireframe_generator - 分析UI图像并生成线框原型设计描述
- wireframe_html - 将文字描述转换为HTML原型界面
- html_to_api_doc - 根据HTML原型和项目描述生成API接口文档（三步流程）
- html_to_vue - 根据HTML原型和API文档生成Vue前端项目
- html_to_springboot - 根据HTML原型和API文档生成Springboot后端项目

## demo 示例
```
 python -m app.main --agent pipeline --image test\test01.png --project pro001
```