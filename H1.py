import os
from openai import OpenAI

# 配置豆包 API


from dotenv import load_dotenv
from config import API_KEY,MODEL_ID,BASE_URL


client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"}
                },
                "required": ["command"]
            }
        }
    }
]

    
def execute_tool(tool_name, tool_input):
    if tool_name == "run_command":
        import subprocess
        result = subprocess.run(tool_input["command"], shell=True, capture_output=True, text=True)
        parts = [f"[exit code: {result.returncode}]"]
        if result.stdout:
            parts.append(f"[stdout]\n{result.stdout}")
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        if not result.stdout and not result.stderr:
            parts.append("[no output]")
        
        return "\n".join(parts)
    return "Unknown tool"

def run_agent(user_task: str):
    messages = [{"role": "user", "content": user_task}]
    max_iterations=50
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model =f"{MODEL_ID}",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        messages.append(response_message)
        
        # Terminal condition: no tool calls
        if not response_message.tool_calls:
            print(f"[DONE] {response_message.content}")
            break
        
        # Tool execution loop
        for tool_call in response_message.tool_calls:
            import json
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"[TOOL] {function_name}({function_args})")
            output = execute_tool(function_name, function_args)
            print(f"[RESULT] {output[:200]}")
            
            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": output,
            })
    # 在 run_agent 末尾,return messages
    # 然后在外面:
    return messages

prompt ="在 Harness_Engineering 里找 README.md "
messages = run_agent(prompt)
import json
import time
with open(f"run_{int(time.time())}.json", "w") as f:
    json.dump([m if isinstance(m, dict) else m.model_dump() for m in messages], f, 
              indent=2, ensure_ascii=False, default=str)


# 启动


#python H1.py


