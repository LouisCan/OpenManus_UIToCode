import asyncio
import sys
from typing import List, Optional

from app.agent.manus import Manus
from app.agent.planning import PlanningAgent
from app.agent.pipeline_agent import PipelineAgent
from app.logger import logger


async def main():
    """主函数，运行Manus代理。"""
    args = sys.argv[1:]  # 获取命令行参数

    # 确定要使用的代理
    agent_type = "manus"  # 默认使用Manus代理
    input_image = None
    project_name = None

    # 解析命令行参数
    i = 0
    while i < len(args):
        if args[i] == "--agent":
            if i + 1 < len(args):
                agent_type = args[i + 1]
                i += 2
            else:
                logger.error("缺少代理类型参数")
                return
        elif args[i] == "--image":
            if i + 1 < len(args):
                input_image = args[i + 1]
                i += 2
            else:
                logger.error("缺少图像路径参数")
                return
        elif args[i] == "--project":
            if i + 1 < len(args):
                project_name = args[i + 1]
                i += 2
            else:
                logger.error("缺少项目名称参数")
                return
        else:
            i += 1

    # 根据指定类型创建代理
    if agent_type == "pipeline" and input_image:
        agent = PipelineAgent()
        logger.info(f"使用Pipeline代理处理图像: {input_image}, 项目名称: {project_name or 'auto_generated_project'}")
        result = await agent.run(input_image_path=input_image, project_name=project_name)
    elif agent_type == "planning":
        agent = PlanningAgent()
        logger.info("使用Planning代理")
        result = await agent.run()
    else:
        agent = Manus()
        logger.info("使用Manus代理")
        result = await agent.run()

    logger.info(f"代理执行结果: {result}")


if __name__ == "__main__":
    """如果作为主程序运行，调用主函数。"""
    asyncio.run(main())
