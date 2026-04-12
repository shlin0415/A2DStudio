import os
from typing import Dict, List, Callable
from ling_chat.core.llm_providers.manager import LLMManager
from ling_chat.utils.load_env import load_env

load_env()

def check_computer_status(arguments: Dict) -> str:
    """
实际上用于占位符，目前没有实际检查，所以这里返回True
    """
    # 在这里填写你要打印的具体内容
    string_to_print = arguments.get('string_to_print', '')
    
    # 执行打印操作
    print(f"工具输出: True")
    
    # 返回字符串给LLM
    return f"True"


def configure_llm_environment():
    """
    配置LLM环境变量
    用户可以根据需要修改这些配置
    """
    # 设置LLM提供程序类型 (例如: openai, gemini, webllm, ollama等)
    os.environ.setdefault("LLM_PROVIDER", "webllm")  # 默认使用webllm，可根据需要修改
    
    # 设置模型类型
    os.environ.setdefault("MODEL_TYPE", "deepseek-chat")  # 默认模型，可根据需要修改
    
    # 设置API密钥 (对于需要认证的提供商)
    os.environ.setdefault("CHAT_API_KEY", "")  # 请在此处填入你的API密钥
    
    # 设置API基础URL (对于自托管或第三方API)
    os.environ.setdefault("CHAT_BASE_URL", "https://api.deepseek.com/v1")  # 默认URL，可根据需要修改
    
    print("LLM环境变量配置完成")


def main():
    # 配置LLM环境
    configure_llm_environment()
    
    # 初始化LLM管理器
    llm_manager = LLMManager()
    
    # 定义工具描述
    # 注意：这里使用了默认的工具名称和描述，你可以根据需要修改它们
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_computer_status",  # 工具名称 - 可据需要修改
                "description": "打印当前电脑是不是正常，支持local和用户指定的其它电脑编号",  # 工具描述 - 可据需要修改
                "parameters": {
                    "type": "object",
                    "properties": {
                        "computer_name": {
                            "type": "string",
                            "description": "需要获取的电脑编号"
                        }
                    },
                    "required": ["computer_name"]
                }
            }
        }
    ]
    
    # 设置消息历史
    messages = [
        {
            "role": "user",
            "content": "请检查现在我的电脑（local）情况"
        }
    ]
    
    # 定义工具执行器
    def tool_executor(tool_name: str, arguments: dict) -> str:
        if tool_name == "check_computer_status":  # 与上面定义的工具名称保持一致
            return check_computer_status(arguments)
        else:
            return f"错误：未知工具 {tool_name}"
    
    # 调用带工具有LLM接口
    response = llm_manager.process_message_with_tools(
        messages=messages,
        tools=tools,
        tool_executor=tool_executor
    )
    
    print("LLM最终响应:", response)


if __name__ == "__main__":
    main()