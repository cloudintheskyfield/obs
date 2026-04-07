#!/usr/bin/env python3
"""完整系统测试脚本"""

import requests
import json
import time

def test_complete_system():
    base_url = "http://127.0.0.1:8000"
    
    print("=== Omni Agent Complete System Test ===")
    print("=" * 50)
    
    # 1. Test health status
    print("\n[1] Testing system health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("[OK] System health: OK")
        else:
            print(f"[FAIL] Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] Cannot connect to system: {e}")
        return False
    
    # 2. Test skills loading
    print("\n[2] Testing skills loading...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=10)
        if response.status_code == 200:
            skills = response.json().get('skills', [])
            print(f"[OK] Successfully loaded {len(skills)} skills:")
            for skill in skills:
                print(f"     {skill['name']}: {skill['description'][:40]}...")
        else:
            print(f"[FAIL] Skills loading failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Skills loading exception: {e}")
    
    # 3. Test file operations
    print("\n[3] Testing file operations...")
    try:
        # Create file
        payload = {
            "tool_name": "str_replace_editor",
            "parameters": {
                "command": "create",
                "path": "test_frontend.py",
                "file_text": "#!/usr/bin/env python3\nprint('Hello from Omni Agent Frontend Test!')\nprint('System running normally')"
            }
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=15)
        if response.status_code == 200 and response.json().get('success'):
            print("[OK] File creation successful")
        else:
            print(f"[FAIL] File creation failed: {response.text}")
        
        # Read file
        payload = {
            "tool_name": "str_replace_editor",
            "parameters": {
                "command": "view",
                "path": "test_frontend.py"
            }
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=15)
        if response.status_code == 200 and response.json().get('success'):
            print("[OK] File reading successful")
        else:
            print(f"[FAIL] File reading failed: {response.text}")
            
    except Exception as e:
        print(f"[FAIL] File operations test failed: {e}")
    
    # 4. Test command execution
    print("\n[4] Testing command execution...")
    try:
        payload = {
            "tool_name": "bash",
            "parameters": {
                "command": "python test_frontend.py"
            }
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=15)
        if response.status_code == 200 and response.json().get('success'):
            result = response.json()
            print("[OK] Command execution successful")
            print(f"     Output: {result.get('content', '')[:100]}...")
        else:
            print(f"[FAIL] Command execution failed: {response.text}")
    except Exception as e:
        print(f"[FAIL] Command execution test failed: {e}")
    
    # 5. 测试前端页面
    print("\n5️⃣  测试前端界面...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            content = response.text
            if "Omni Agent" in content and "<!DOCTYPE html>" in content:
                print("✅ 前端页面加载成功")
                print(f"   📄 页面大小: {len(content)} 字符")
            else:
                print("❓ 前端页面内容异常")
        else:
            print(f"❌ 前端页面加载失败: {response.status_code}")
    except Exception as e:
        print(f"❌ 前端测试失败: {e}")
    
    # 6. 测试API文档
    print("\n6️⃣  测试API文档...")
    try:
        response = requests.get(f"{base_url}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ API文档可用")
        else:
            print(f"❌ API文档不可用: {response.status_code}")
    except Exception as e:
        print(f"❌ API文档测试失败: {e}")
    
    # 7. 性能测试
    print("\n7️⃣  性能测试...")
    try:
        start_time = time.time()
        payload = {
            "tool_name": "bash", 
            "parameters": {"command": "echo 'Performance Test'"}
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=15)
        end_time = time.time()
        
        if response.status_code == 200 and response.json().get('success'):
            response_time = (end_time - start_time) * 1000
            print(f"✅ 响应时间: {response_time:.1f}ms")
            if response_time < 1000:
                print("   🚀 性能优秀")
            elif response_time < 3000:
                print("   ⚡ 性能良好") 
            else:
                print("   🐌 性能需要优化")
        else:
            print("❌ 性能测试失败")
    except Exception as e:
        print(f"❌ 性能测试异常: {e}")
    
    print("\n" + "=" * 50)
    print("🎉 系统测试完成!")
    print("\n📋 使用说明:")
    print("   🌐 前端界面: http://127.0.0.1:8000")
    print("   📖 API文档: http://127.0.0.1:8000/docs")
    print("   💻 命令行: python chat_interface.py")
    print("\n🛠️  支持的操作:")
    print("   • 文件操作: file:create test.txt Hello World")
    print("   • 命令执行: cmd:ls -la")
    print("   • 计算机操作: screenshot")
    print("   • 自然语言: 帮我创建一个Python脚本")
    
    return True

if __name__ == "__main__":
    test_complete_system()